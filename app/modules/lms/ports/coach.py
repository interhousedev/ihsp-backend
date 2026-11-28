"""Ports of the Coach: sessions, solution keys, the learner's attempt, the model."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from app.modules.lms.domain.learning.coach import SolutionKey, TutorSession


@dataclass(frozen=True, slots=True)
class AttemptSnapshot:
    """What the learner last did on the block (`left` None: unlimited attempts)."""

    made: int
    left: int | None
    wrong: bool
    last_answer: str | None


@dataclass(frozen=True, slots=True)
class CoachMessage:
    """One chat message sent to the model."""

    role: str
    text: str


@dataclass(frozen=True, slots=True)
class ModelReply:
    """The structured answer of the Coach model."""

    message: str
    hint_level: int
    ask_back: bool


@dataclass(frozen=True, slots=True)
class CoachInsightRow:
    """The sessions of one step in a period."""

    step_id: UUID
    sessions: int
    resolved: int
    escalated: int
    max_hint_level: int


class TutorSessionRepository(Protocol):
    """Stores sessions; every lookup is scoped by the learner."""

    async def add(self, user_id: UUID, session: TutorSession) -> None:
        """Insert a new session."""
        ...

    async def save(self, user_id: UUID, session: TutorSession) -> None:
        """Persist the session and its turns."""
        ...

    async def get_for_user(
        self, session_id: UUID, user_id: UUID
    ) -> TutorSession | None:
        """Return the session, or None for another learner's id."""
        ...

    async def latest_for_step(
        self, user_id: UUID, step_id: UUID
    ) -> TutorSession | None:
        """Return the learner's newest session on the step."""
        ...


class SolutionKeyRepository(Protocol):
    """Solution keys stored with a step revision."""

    async def for_revision(self, revision_id: UUID) -> list[SolutionKey]:
        """Return the keys of one revision only."""
        ...


class SolutionKeyStore(SolutionKeyRepository, Protocol):
    """Solution keys that staff may also replace."""

    async def replace(self, revision_id: UUID, keys: list[SolutionKey]) -> None:
        """Store the keys of a revision."""
        ...


class AttemptReader(Protocol):
    """Reads the learner's last attempt at a block."""

    async def last_attempt(
        self, user_id: UUID, step_id: UUID, block_id: str | None
    ) -> AttemptSnapshot:
        """Return the snapshot (made 0 when the learner has not tried)."""
        ...


class CoachModel(Protocol):
    """One Coach turn of the model (AI task LMS_TUTOR)."""

    async def reply(
        self,
        messages: list[CoachMessage],
        secret_steps: list[str],
        attempt: AttemptSnapshot,
    ) -> ModelReply:
        """Return the structured reply."""
        ...


class LmsEvents(Protocol):
    """Writes outbox events."""

    async def publish(self, name: str, payload: dict[str, Any]) -> None:
        """Queue an event for the outbox."""
        ...


class CoachInsights(Protocol):
    """Aggregates the sessions of a course."""

    async def for_course(
        self, course_id: UUID, start: datetime | None, end: datetime | None
    ) -> list[CoachInsightRow]:
        """Return one row per step with sessions in the period."""
        ...
