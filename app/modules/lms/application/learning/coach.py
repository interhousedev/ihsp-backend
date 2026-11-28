"""Use cases of the Coach: open a session, take a turn, close it (spec 2.4).

Every turn runs the gate again (enrolment, audience, tutor switch), the message
bounds and the daily limit; the model gets only the teacher-approved solution
steps of the revision the session opened on and never a final answer.
"""

from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any, Final, Protocol
from uuid import UUID

from app.modules.lms.domain.learning.coach import (
    MAX_HINT_LEVEL,
    CoachMode,
    CoachOutcome,
    TutorSession,
    leaks_answer,
    prompt_steps,
)
from app.modules.lms.domain.learning.lesson_ai import TUTOR_MESSAGE_MAX_CHARS
from app.modules.lms.domain.learning.tutor_errors import TutorDisabledError
from app.modules.lms.ports.coach import (
    AttemptReader,
    CoachMessage,
    CoachModel,
    LmsEvents,
    SolutionKeyRepository,
    TutorSessionRepository,
)
from app.shared.actor import Actor
from app.shared.base_error import ValidationFailedError
from app.shared.clock import Clock

from uuid_utils.compat import uuid7

RESOLVED_XP: Final = 5
LEAK_REPLACEMENT: Final = (
    "Let's think it through together: what is your next step? / "
    "Давайте подумаем вместе: каким будет ваш следующий шаг? / "
    "Keling, birga oʼylab koʼraylik: keyingi qadamingiz qanday?"
)


class CoachTrigger(StrEnum):
    """What made the learner open the Coach."""

    LEARNER_TAP = "learner_tap"
    WRONG_ANSWER = "wrong_answer"
    ATTEMPTS_EXHAUSTED = "attempts_exhausted"
    IDLE = "idle"


_MODE: Final = {
    CoachTrigger.LEARNER_TAP: CoachMode.ASK,
    CoachTrigger.WRONG_ANSWER: CoachMode.REMEDIATE,
    CoachTrigger.ATTEMPTS_EXHAUSTED: CoachMode.REMEDIATE,
    CoachTrigger.IDLE: CoachMode.HINT,
}


class CoachGate(Protocol):
    """Access of a learner to the Coach of a step; returns the live revision id."""

    async def require(self, actor: Actor, step_id: UUID) -> UUID:
        """Raise unless the actor may use the Coach on the step."""
        ...


class CoachLimiter(Protocol):
    """The daily cap of the learner."""

    async def hit(self, actor: Actor) -> None:
        """Count one model call; raise TutorDailyLimitError over the cap."""
        ...


@dataclass(frozen=True, slots=True)
class TutorSessionView:
    """A session as the learner sees it."""

    id: UUID
    mode: str
    hint_level: int
    closed: bool


@dataclass(frozen=True, slots=True)
class CoachTurnView:
    """One stored message."""

    role: str
    text: str
    hint_level: int


@dataclass(frozen=True, slots=True)
class CoachReplyView:
    """The Coach's answer to a turn."""

    message: str
    hint_level: int
    ask_back: bool


def _view(session: TutorSession) -> TutorSessionView:
    return TutorSessionView(
        id=session.id,
        mode=session.mode.value,
        hint_level=session.hint_level,
        closed=session.is_closed,
    )


class OpenCoach:
    """Open a Coach session on a step."""

    def __init__(
        self,
        sessions: TutorSessionRepository,
        attempts: AttemptReader,
        gate: CoachGate,
        clock: Clock,
    ) -> None:
        """Store collaborators."""
        self.sessions = sessions
        self.attempts = attempts
        self.gate = gate
        self.clock = clock

    async def execute(
        self,
        actor: Actor,
        step_id: UUID,
        block_id: str | None,
        trigger: CoachTrigger,
    ) -> TutorSessionView:
        """Open a session bound to the live revision of the step."""
        revision_id = await self.gate.require(actor, step_id)
        session = TutorSession.open(
            uuid7(),
            None,
            step_id,
            block_id,
            _MODE[trigger],
            self.clock.now(),
            revision_id,
        )
        await self.sessions.add(actor.user_id, session)
        return _view(session)


class CoachReply:
    """Take one turn of a session."""

    def __init__(
        self,
        sessions: TutorSessionRepository,
        keys: SolutionKeyRepository,
        attempts: AttemptReader,
        model: CoachModel | None,
        gate: CoachGate,
        limiter: CoachLimiter,
        clock: Clock,
    ) -> None:
        """Store collaborators; ``model`` is set late when the AI module exists."""
        self.sessions = sessions
        self.keys = keys
        self.attempts = attempts
        self.model = model
        self.gate = gate
        self.limiter = limiter
        self.clock = clock

    async def execute(
        self, actor: Actor, session_id: UUID, message: str
    ) -> CoachReplyView:
        """Answer the learner's message and store both turns."""
        return await self._turn(actor, session_id, message)

    async def hint(self, actor: Actor, session_id: UUID) -> CoachReplyView:
        """Give the next rung of the hint ladder (at most ``MAX_HINT_LEVEL``)."""
        session = await self.sessions.get_for_user(session_id, actor.user_id)
        if session is None:
            raise LookupError(str(session_id))
        if session.hint_level >= MAX_HINT_LEVEL:
            raise ValidationFailedError(params={"field": "hint_level"})
        target = session.hint_level + 1
        return await self._turn(
            actor,
            session_id,
            f"Give me the next hint (level {target}).",
            min_level=target,
        )

    async def explain_mistake(
        self, actor: Actor, session_id: UUID, answer: str
    ) -> CoachReplyView:
        """Explain what is wrong in the learner's answer without giving the solution."""
        return await self._turn(
            actor,
            session_id,
            f"Explain what is wrong in my answer: {answer.strip()}",
            answer=answer.strip(),
        )

    async def _turn(
        self,
        actor: Actor,
        session_id: UUID,
        message: str,
        *,
        min_level: int = 0,
        answer: str | None = None,
    ) -> CoachReplyView:
        session = await self.sessions.get_for_user(session_id, actor.user_id)
        if session is None:
            raise LookupError(str(session_id))
        await self.gate.require(actor, session.step_id)
        text = message.strip()
        if not text or len(text) > TUTOR_MESSAGE_MAX_CHARS:
            raise ValidationFailedError(params={"field": "message"})
        await self.limiter.hit(actor)
        if self.model is None:
            raise TutorDisabledError()
        keys = (
            await self.keys.for_revision(session.revision_id)
            if session.revision_id is not None
            else []
        )
        attempt = await self.attempts.last_attempt(
            actor.user_id, session.step_id, session.block_id
        )
        if answer is not None:
            attempt = replace(attempt, last_answer=answer, wrong=True)
        if not attempt.wrong:
            attempt = replace(attempt, last_answer=None)
        history = [CoachMessage(t.role, t.text) for t in session.turns]
        history.append(CoachMessage("learner", text))
        reply = await self.model.reply(history, prompt_steps(keys), attempt)
        answers = [a for key in keys for a in key.answers]
        filtered = leaks_answer(reply.message, answers)
        out = LEAK_REPLACEMENT if filtered else reply.message.strip()
        now = self.clock.now()
        session.record_turn(
            "learner",
            text,
            session.hint_level,
            attempts_made=attempt.made,
            attempts_left=attempt.left,
            at=now,
        )
        session.record_turn(
            "tutor",
            out,
            min(MAX_HINT_LEVEL, max(reply.hint_level, session.hint_level, min_level)),
            attempts_made=attempt.made,
            attempts_left=attempt.left,
            at=now,
        )
        await self.sessions.save(actor.user_id, session)
        return CoachReplyView(
            message=out, hint_level=session.hint_level, ask_back=reply.ask_back
        )


class CloseCoach:
    """Close a session exactly once and tell the rest of the platform."""

    def __init__(
        self, sessions: TutorSessionRepository, events: LmsEvents, clock: Clock
    ) -> None:
        """Store collaborators."""
        self.sessions = sessions
        self.events = events
        self.clock = clock

    async def execute(
        self, actor: Actor, session_id: UUID, outcome: CoachOutcome
    ) -> CoachOutcome:
        """Close the session; a repeat returns the stored outcome silently."""
        session = await self.sessions.get_for_user(session_id, actor.user_id)
        if session is None:
            raise LookupError(str(session_id))
        if session.is_closed and session.outcome is not None:
            return session.outcome
        session.close(outcome, self.clock.now())
        await self.sessions.save(actor.user_id, session)
        payload: dict[str, Any] = {
            "session_id": str(session.id),
            "user_id": str(actor.user_id),
            "step_id": str(session.step_id),
            "dedup_key": str(session.id),
            "outcome": outcome.value,
            "xp": RESOLVED_XP if outcome is CoachOutcome.RESOLVED else 0,
        }
        await self.events.publish("lms.coach.session_closed", payload)
        if outcome is CoachOutcome.ESCALATED:
            await self.events.publish("lms.coach.escalated", dict(payload))
        return outcome


@dataclass(frozen=True, slots=True)
class LatestCoachView:
    """The newest session of the learner on a step with its messages."""

    session: TutorSessionView
    turns: list[CoachTurnView]


class LatestCoach:
    """Return the learner's newest session on a step, if any."""

    def __init__(self, sessions: TutorSessionRepository, gate: CoachGate) -> None:
        """Store collaborators."""
        self.sessions = sessions
        self.gate = gate

    async def execute(self, actor: Actor, step_id: UUID) -> LatestCoachView | None:
        """Return the session or None."""
        await self.gate.require(actor, step_id)
        session = await self.sessions.latest_for_step(actor.user_id, step_id)
        if session is None:
            return None
        return LatestCoachView(
            _view(session),
            [CoachTurnView(t.role, t.text, t.hint_level) for t in session.turns],
        )
