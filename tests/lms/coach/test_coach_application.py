"""Coach use cases with in-memory fakes (spec 2.4).

The implementation must provide:
  app.modules.lms.application.learning.coach:
    OpenCoach(sessions, attempts, gate, clock).execute(actor, step_id, block_id,
    trigger)
      -> TutorSessionView(id, mode, hint_level, closed)
      The session is bound to the live revision id returned by `gate.require`
      (the gate also enforces tutor_enabled, locked/hidden step, enrolment, AI access).
    CoachReply(sessions, keys, attempts, model, gate, limiter, clock)
      .execute(actor, session_id, message) -> CoachReplyView(message, hint_level,
      ask_back)
      Re-runs `gate.require` on every turn (revoked enrolment / AI access stops the
      session), rejects an empty or over-TUTOR_MESSAGE_MAX_CHARS message with
      ValidationFailedError, and calls `limiter.hit(actor)` (the runtime LimitsProvider
      daily cap of the old AskTutor; raises TutorDailyLimitError) before the model.
      Keys come from `keys.for_revision(session.revision_id)`: a key of another revision
      (an approved draft, or a revision published after the session opened) never
      reaches
      the prompt. The model never sees the learner's answer once it is correct
      (attempt.wrong False => last_answer None) and never a key's `answers`.
    CloseCoach(sessions, events, clock).execute(actor, session_id, outcome)
      Exactly once: a second close (replay, concurrent) returns the stored outcome and
      publishes nothing. Every outcome publishes 'lms.coach.session_closed' (escalated
      also 'lms.coach.escalated'); the payload carries dedup_key == session_id so the XP
      consumer applies the daily cap durably. Sessions are persisted via
      `sessions.save(user_id, session)` after each turn and close.
    CoachTrigger (learner_tap|wrong_answer|attempts_exhausted|idle)
  ports in app.modules.lms.ports.coach:
    TutorSessionRepository: add(session), save(user_id, session),
    get_for_user(session_id, user_id) -> session|None
        (None for another learner's id: the IDOR check lives in the query),
        latest_for_step(user_id, step_id)
    SolutionKeyRepository: for_revision(revision_id) -> list[SolutionKey]
    AttemptReader: last_attempt(user_id, step_id, block_id) -> AttemptSnapshot(made,
    left, wrong, last_answer)
    CoachModel: reply(messages, secret_steps, attempt) -> ModelReply(message,
    hint_level, ask_back)
    LmsEvents: publish(name: str, payload: dict) (outbox writer)
  a missing/foreign session raises LookupError (route maps to 404).
  errors: app.modules.lms.domain.learning.errors.NotEnrolledError,
          app.modules.lms.domain.learning.tutor_errors.TutorDisabledError
Boring choices: trigger maps to mode (wrong_answer/attempts_exhausted -> remediate,
learner_tap -> ask, idle -> hint); 'lms.coach.session_closed' payload carries
{session_id, dedup_key, outcome, xp: 5 when resolved else 0}; escalated closes
publish both events. Fakes are defined here so the tests do not depend on infra.
"""

import copy
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from app.modules.lms.application.learning.coach import (
    CloseCoach,
    CoachReply,
    CoachTrigger,
    OpenCoach,
)
from app.modules.lms.domain.learning.coach import (
    CoachOutcome,
    HintLockedError,
    KeyStatus,
    SolutionKey,
    TutorSession,
)
from app.modules.lms.domain.learning.errors import NotEnrolledError
from app.modules.lms.domain.learning.tutor_errors import (
    TutorDailyLimitError,
    TutorDisabledError,
)
from app.modules.lms.ports.coach import AttemptSnapshot, ModelReply
from app.shared.base_error import ValidationFailedError

import pytest

NOW = datetime(2026, 11, 27, 9, tzinfo=UTC)


@dataclass
class Actor:
    user_id: UUID = field(default_factory=uuid4)


class Clock:
    def now(self) -> datetime:
        return NOW


class Sessions:
    def __init__(self) -> None:
        self.rows: dict[UUID, tuple[UUID, TutorSession]] = {}

    async def add(self, user_id: UUID, session: TutorSession) -> None:
        self.rows[session.id] = (user_id, copy.deepcopy(session))

    async def save(self, user_id: UUID, session: TutorSession) -> None:
        self.rows[session.id] = (user_id, copy.deepcopy(session))

    async def get_for_user(
        self, session_id: UUID, user_id: UUID
    ) -> TutorSession | None:
        """A detached copy, like a real repository: unsaved changes are lost."""
        row = self.rows.get(session_id)
        return copy.deepcopy(row[1]) if row and row[0] == user_id else None


class Events:
    def __init__(self) -> None:
        self.published: list[tuple[str, dict[str, Any]]] = []

    async def publish(self, name: str, payload: dict[str, Any]) -> None:
        self.published.append((name, payload))


class Attempts:
    def __init__(self, snap: AttemptSnapshot) -> None:
        self.snap = snap

    async def last_attempt(
        self, user_id: UUID, step_id: UUID, block_id: str | None
    ) -> AttemptSnapshot:
        return self.snap


REVISION = uuid4()
OTHER_REVISION = uuid4()


class Keys:
    def __init__(self, keys: list[SolutionKey], revision: UUID = REVISION) -> None:
        self.by_revision = {revision: keys}

    async def for_revision(self, revision_id: UUID) -> list[SolutionKey]:
        return self.by_revision.get(revision_id, [])


class Model:
    def __init__(self, level: int = 3, message: str = "Try step one") -> None:
        self.level, self.message = level, message
        self.seen: list[Any] = []

    async def reply(
        self, messages: Any, secret_steps: list[str], attempt: AttemptSnapshot
    ) -> ModelReply:
        self.seen.append((messages, secret_steps, attempt))
        return ModelReply(message=self.message, hint_level=self.level, ask_back=True)


class Gate:
    """Mirrors require_step + enrolment + tutor_enabled; returns the live revision."""

    def __init__(self, enrolled: bool = True, tutor_enabled: bool = True) -> None:
        self.enrolled, self.tutor_enabled = enrolled, tutor_enabled

    async def require(self, actor: Actor, step_id: UUID) -> UUID:
        if not self.enrolled:
            raise NotEnrolledError()
        if not self.tutor_enabled:
            raise TutorDisabledError()
        return REVISION


class Limiter:
    def __init__(self, left: int | None = None) -> None:
        self.left = left

    async def hit(self, actor: Actor) -> None:
        if self.left is not None:
            if self.left <= 0:
                raise TutorDailyLimitError()
            self.left -= 1


def _reply(
    sessions: Sessions,
    keys: Keys,
    attempt: AttemptSnapshot,
    model: Model,
    gate: Gate | None = None,
    limiter: Limiter | None = None,
) -> CoachReply:
    return CoachReply(
        sessions,
        keys,
        Attempts(attempt),
        model,
        gate or Gate(),
        limiter or Limiter(),
        Clock(),
    )


async def _open(
    sessions: Sessions, actor: Actor, attempt: AttemptSnapshot, trigger: CoachTrigger
) -> Any:
    return await OpenCoach(sessions, Attempts(attempt), Gate(), Clock()).execute(
        actor, uuid4(), "quiz", trigger
    )


FRESH = AttemptSnapshot(made=0, left=3, wrong=False, last_answer=None)
WRONG = AttemptSnapshot(made=1, left=2, wrong=True, last_answer="5")


async def test_open_creates_a_session_owned_by_the_learner() -> None:
    sessions, actor = Sessions(), Actor()
    view = await _open(sessions, actor, WRONG, CoachTrigger.WRONG_ANSWER)
    assert view.hint_level == 0 and not view.closed
    assert await sessions.get_for_user(view.id, actor.user_id) is not None


async def test_another_learner_cannot_load_the_session() -> None:
    """IDOR: lookup is scoped by user id in the repository."""
    sessions, actor = Sessions(), Actor()
    view = await _open(sessions, actor, WRONG, CoachTrigger.WRONG_ANSWER)
    assert await sessions.get_for_user(view.id, uuid4()) is None


async def test_open_requires_enrolment() -> None:
    with pytest.raises(NotEnrolledError):
        await OpenCoach(Sessions(), Attempts(FRESH), Gate(False), Clock()).execute(
            Actor(), uuid4(), None, CoachTrigger.LEARNER_TAP
        )


async def test_reply_sends_only_approved_steps_and_the_last_attempt() -> None:
    sessions, actor, model = Sessions(), Actor(), Model(level=1)
    view = await _open(sessions, actor, WRONG, CoachTrigger.WRONG_ANSWER)
    step = uuid4()
    keys = Keys(
        [
            SolutionKey(step, "quiz", "q1", ["approved step"], [], KeyStatus.APPROVED),
            SolutionKey(step, "quiz", "q2", ["draft step"], [], KeyStatus.DRAFT),
        ]
    )
    await _reply(sessions, keys, WRONG, model).execute(actor, view.id, "I am stuck")
    _, secret, attempt = model.seen[0]
    assert secret == ["approved step"]
    assert attempt.last_answer == "5"


async def test_reply_that_leaks_the_answer_is_replaced() -> None:
    sessions, actor = Sessions(), Actor()
    view = await _open(sessions, actor, WRONG, CoachTrigger.WRONG_ANSWER)
    keys = Keys(
        [
            SolutionKey(
                uuid4(), "quiz", "q1", ["s"], [], KeyStatus.APPROVED, answers=["42"]
            )
        ]
    )
    out = await _reply(sessions, keys, WRONG, Model(1, "The answer is 42")).execute(
        actor, view.id, "tell me"
    )
    assert "42" not in out.message


async def test_level_3_is_refused_before_any_attempt() -> None:
    sessions, actor = Sessions(), Actor()
    view = await _open(sessions, actor, FRESH, CoachTrigger.LEARNER_TAP)
    with pytest.raises(HintLockedError):
        await _reply(sessions, Keys([]), FRESH, Model(3)).execute(
            actor, view.id, "just show me"
        )


async def test_level_3_allowed_when_attempts_are_exhausted() -> None:
    sessions, actor = Sessions(), Actor()
    spent = AttemptSnapshot(made=0, left=0, wrong=True, last_answer=None)
    view = await _open(sessions, actor, spent, CoachTrigger.ATTEMPTS_EXHAUSTED)
    out = await _reply(sessions, Keys([]), spent, Model(3)).execute(
        actor, view.id, "help"
    )
    assert out.hint_level == 3


@pytest.mark.parametrize(
    ("outcome", "xp", "extra"),
    [
        (CoachOutcome.RESOLVED, 5, []),
        (CoachOutcome.ABANDONED, 0, []),
        (CoachOutcome.ESCALATED, 0, ["lms.coach.escalated"]),
    ],
)
async def test_every_close_publishes_session_closed(
    outcome: CoachOutcome, xp: int, extra: list[str]
) -> None:
    sessions, actor, events = Sessions(), Actor(), Events()
    view = await _open(sessions, actor, WRONG, CoachTrigger.WRONG_ANSWER)
    await CloseCoach(sessions, events, Clock()).execute(actor, view.id, outcome)
    names = [n for n, _ in events.published]
    assert names.count("lms.coach.session_closed") == 1
    assert all(e in names for e in extra)
    closed = next(p for n, p in events.published if n == "lms.coach.session_closed")
    assert closed["xp"] == xp and closed["outcome"] == outcome.value
    assert str(closed["dedup_key"]) == str(view.id)
    stored = await sessions.get_for_user(view.id, actor.user_id)
    assert stored is not None and stored.outcome == outcome and stored.closed_at


async def test_closing_twice_publishes_once_and_keeps_the_first_outcome() -> None:
    sessions, actor, events = Sessions(), Actor(), Events()
    view = await _open(sessions, actor, WRONG, CoachTrigger.WRONG_ANSWER)
    close = CloseCoach(sessions, events, Clock())
    await close.execute(actor, view.id, CoachOutcome.ABANDONED)
    await close.execute(actor, view.id, CoachOutcome.RESOLVED)
    assert len(events.published) == 1
    stored = await sessions.get_for_user(view.id, actor.user_id)
    assert stored is not None and stored.outcome == CoachOutcome.ABANDONED


async def test_turns_are_persisted() -> None:
    sessions, actor = Sessions(), Actor()
    view = await _open(sessions, actor, WRONG, CoachTrigger.WRONG_ANSWER)
    await _reply(sessions, Keys([]), WRONG, Model(1)).execute(actor, view.id, "hi")
    stored = await sessions.get_for_user(view.id, actor.user_id)
    assert stored is not None and len(stored.turns) == 2 and stored.hint_level == 1


async def test_keys_of_another_revision_never_reach_the_prompt() -> None:
    sessions, actor, model = Sessions(), Actor(), Model(1)
    view = await _open(sessions, actor, WRONG, CoachTrigger.WRONG_ANSWER)
    key = SolutionKey(uuid4(), "quiz", "q1", ["new draft rev"], [], KeyStatus.APPROVED)
    keys = Keys([key], revision=OTHER_REVISION)
    await _reply(sessions, keys, WRONG, model).execute(actor, view.id, "help")
    assert model.seen[0][1] == []


async def test_correct_answer_is_not_sent_to_the_model() -> None:
    sessions, actor, model = Sessions(), Actor(), Model(1)
    right = AttemptSnapshot(made=1, left=2, wrong=False, last_answer="42")
    view = await _open(sessions, actor, right, CoachTrigger.LEARNER_TAP)
    await _reply(sessions, Keys([]), right, model).execute(actor, view.id, "why?")
    assert model.seen[0][2].last_answer is None


async def test_model_never_sees_key_answers() -> None:
    sessions, actor, model = Sessions(), Actor(), Model(1)
    view = await _open(sessions, actor, WRONG, CoachTrigger.WRONG_ANSWER)
    key = SolutionKey(
        uuid4(), "quiz", "q1", ["step"], [], KeyStatus.APPROVED, answers=["42"]
    )
    await _reply(sessions, Keys([key]), WRONG, model).execute(actor, view.id, "help")
    assert "42" not in repr(model.seen[0])


# ---- preserved safety controls of the old AskTutor ----------------------------


async def test_tutor_disabled_course_cannot_open() -> None:
    gate = Gate(tutor_enabled=False)
    with pytest.raises(TutorDisabledError):
        await OpenCoach(Sessions(), Attempts(FRESH), gate, Clock()).execute(
            Actor(), uuid4(), None, CoachTrigger.LEARNER_TAP
        )


async def test_revoked_enrolment_stops_an_open_session() -> None:
    sessions, actor = Sessions(), Actor()
    view = await _open(sessions, actor, WRONG, CoachTrigger.WRONG_ANSWER)
    with pytest.raises(NotEnrolledError):
        await _reply(
            sessions, Keys([]), WRONG, Model(1), gate=Gate(enrolled=False)
        ).execute(actor, view.id, "hi")


async def test_daily_limit_blocks_the_model_call() -> None:
    sessions, actor, model = Sessions(), Actor(), Model(1)
    view = await _open(sessions, actor, WRONG, CoachTrigger.WRONG_ANSWER)
    with pytest.raises(TutorDailyLimitError):
        await _reply(sessions, Keys([]), WRONG, model, limiter=Limiter(0)).execute(
            actor, view.id, "hi"
        )
    assert model.seen == []


@pytest.mark.parametrize("message", ["", "   ", "x" * 5000])
async def test_message_bounds(message: str) -> None:
    sessions, actor, model = Sessions(), Actor(), Model(1)
    view = await _open(sessions, actor, WRONG, CoachTrigger.WRONG_ANSWER)
    with pytest.raises(ValidationFailedError):
        await _reply(sessions, Keys([]), WRONG, model).execute(actor, view.id, message)
    assert model.seen == []


async def test_closing_another_learners_session_is_not_found() -> None:
    sessions, actor = Sessions(), Actor()
    view = await _open(sessions, actor, WRONG, CoachTrigger.WRONG_ANSWER)
    with pytest.raises(LookupError):
        await CloseCoach(sessions, Events(), Clock()).execute(
            Actor(), view.id, CoachOutcome.RESOLVED
        )


async def test_hint_climbs_the_ladder_to_three_then_stops() -> None:
    sessions, actor = Sessions(), Actor()
    spent = AttemptSnapshot(made=2, left=0, wrong=True, last_answer="1")
    view = await _open(sessions, actor, spent, CoachTrigger.ATTEMPTS_EXHAUSTED)
    reply = _reply(sessions, Keys([]), spent, Model(0))
    levels = [(await reply.hint(actor, view.id)).hint_level for _ in range(3)]
    assert levels == [1, 2, 3]
    with pytest.raises(ValidationFailedError):
        await reply.hint(actor, view.id)


async def test_explain_mistake_shows_the_answer_to_the_model() -> None:
    sessions, actor, model = Sessions(), Actor(), Model(1)
    view = await _open(sessions, actor, FRESH, CoachTrigger.LEARNER_TAP)
    out = await _reply(sessions, Keys([]), FRESH, model).explain_mistake(
        actor, view.id, "x = 7"
    )
    assert out.message
    assert model.seen[0][2].last_answer == "x = 7"


async def test_hint_of_a_foreign_session_is_not_found() -> None:
    with pytest.raises(LookupError):
        await _reply(Sessions(), Keys([]), FRESH, Model(0)).hint(Actor(), uuid4())
