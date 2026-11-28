"""The Coach: scaffolded tutoring sessions, solution keys and the answer filter.

Rules (spec 2.4): the ladder of hints never goes down, the worked step (level 3)
needs one learner attempt first, only teacher-approved solution steps reach the
model, and a reply that contains a final answer is never sent.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Final
from uuid import UUID

from app.shared.base_error import ConflictError, ForbiddenError

MAX_HINT_LEVEL: Final = 3
WORKED_STEP_LEVEL: Final = 3


class CoachMode(StrEnum):
    """Why the session was opened."""

    ASK = "ask"
    HINT = "hint"
    REMEDIATE = "remediate"
    RECAP = "recap"


class CoachOutcome(StrEnum):
    """How a session ended."""

    RESOLVED = "resolved"
    ABANDONED = "abandoned"
    ESCALATED = "escalated"


class KeyStatus(StrEnum):
    """A key is a draft until the teacher approves it."""

    DRAFT = "draft"
    APPROVED = "approved"


class HintLevelRegressionError(ConflictError):
    """The hint level of a session may only go up."""

    code = "lms/coach-hint-regression"
    message_key = "lms-coach-hint-regression"


class HintLockedError(ForbiddenError):
    """A worked step needs one attempt of the learner first."""

    code = "lms/coach-hint-locked"
    message_key = "lms-coach-hint-locked"


class SessionClosedError(ConflictError):
    """The session is closed."""

    code = "lms/coach-session-closed"
    message_key = "lms-coach-session-closed"


@dataclass(frozen=True, slots=True)
class Misconception:
    """A typical mistake and the nudge that addresses it."""

    pattern: str
    nudge: str


@dataclass(frozen=True, slots=True)
class SolutionKey:
    """Author-written solution of one question.

    ``answers`` are the final answers: they feed the output filter and are never
    put into a prompt.
    """

    step_id: UUID
    block_id: str
    question_id: str
    steps: list[str]
    misconceptions: list[Misconception]
    status: KeyStatus
    answers: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class TutorTurn:
    """One message of a session."""

    session_id: UUID
    role: str
    text: str
    hint_level: int
    citations: list[str]
    created_at: datetime


@dataclass(slots=True)
class TutorSession:
    """A tutoring conversation of one learner on one step."""

    id: UUID
    enrollment_id: UUID | None
    step_id: UUID
    block_id: str | None
    mode: CoachMode
    opened_at: datetime
    revision_id: UUID | None = None
    closed_at: datetime | None = None
    outcome: CoachOutcome | None = None
    turns: list[TutorTurn] = field(default_factory=list)
    hint_level: int = 0

    @classmethod
    def open(
        cls,
        id: UUID,
        enrollment_id: UUID | None,
        step_id: UUID,
        block_id: str | None,
        mode: CoachMode,
        opened_at: datetime,
        revision_id: UUID | None = None,
    ) -> "TutorSession":
        """Return a new open session."""
        return cls(
            id=id,
            enrollment_id=enrollment_id,
            step_id=step_id,
            block_id=block_id,
            mode=mode,
            opened_at=opened_at,
            revision_id=revision_id,
        )

    @property
    def is_closed(self) -> bool:
        """Whether the session no longer takes turns."""
        return self.closed_at is not None

    def record_turn(
        self,
        role: str,
        text: str,
        hint_level: int,
        *,
        attempts_made: int,
        attempts_left: int | None,
        at: datetime,
        citations: Sequence[str] = (),
    ) -> TutorTurn:
        """Append a turn; tutor turns move the ladder, learner turns do not."""
        if self.is_closed:
            raise SessionClosedError()
        if not 0 <= hint_level <= MAX_HINT_LEVEL:
            raise ValueError("hint level out of range")
        if role == "tutor":
            if hint_level < self.hint_level:
                raise HintLevelRegressionError()
            worked = hint_level >= WORKED_STEP_LEVEL
            if worked and attempts_made < 1 and attempts_left != 0:
                raise HintLockedError()
            self.hint_level = hint_level
        turn = TutorTurn(self.id, role, text, hint_level, list(citations), at)
        self.turns.append(turn)
        return turn

    def close(self, outcome: CoachOutcome, at: datetime) -> None:
        """Close the session once."""
        if self.is_closed:
            raise SessionClosedError()
        self.closed_at = at
        self.outcome = outcome


def prompt_steps(keys: Sequence[SolutionKey]) -> list[str]:
    """Return the solution steps of the approved keys; never an answer."""
    return [s for key in keys if key.status is KeyStatus.APPROVED for s in key.steps]


def _norm(value: str) -> str:
    return " ".join(value.casefold().split())


def leaks_answer(reply: str, answers: Sequence[str]) -> bool:
    """Whether the reply contains one of the final answers (a floor, not a proof)."""
    text = _norm(reply)
    for answer in answers:
        needle = _norm(answer)
        if not needle:
            continue
        if re.search(rf"(?<!\w){re.escape(needle)}(?!\w)", text):
            return True
    return False


def step_leaks_answer(step: str, answers: Sequence[str]) -> bool:
    """Whether a solution step states one of the key's own answers."""
    return leaks_answer(step, answers)
