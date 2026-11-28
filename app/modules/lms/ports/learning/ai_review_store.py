"""Port: storage of AI review conversations."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Protocol
from uuid import UUID

AiReviewStatus = Literal["open", "reviewed"]
AiReviewRole = Literal["student", "assistant"]
AiReviewKind = Literal["chat", "question", "review"]


@dataclass(frozen=True, slots=True)
class AiReviewSessionRecord:
    """One conversation of a student about one AI review block."""

    id: UUID
    course_id: UUID
    step_id: UUID
    block_id: str
    user_id: UUID
    status: AiReviewStatus
    submissions_used: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class AiReviewMessageRecord:
    """A stored message; ``history`` is the filtered text the model sees again."""

    id: UUID
    session_id: UUID
    role: AiReviewRole
    kind: AiReviewKind
    text: str | None
    openui: str | None
    history: str
    attachments: list[dict[str, Any]] = field(default_factory=list)
    created_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class NewAiReviewMessage:
    """A message to append."""

    role: AiReviewRole
    kind: AiReviewKind
    text: str | None
    openui: str | None
    history: str
    attachments: list[dict[str, Any]] = field(default_factory=list)


class AiReviewStore(Protocol):
    """Sessions and messages of the AI review block (schema ``lms``)."""

    async def create_session(
        self, *, course_id: UUID, step_id: UUID, block_id: str, user_id: UUID
    ) -> AiReviewSessionRecord:
        """Insert an open session."""
        ...

    async def get_session(self, session_id: UUID) -> AiReviewSessionRecord | None:
        """Return the session or None."""
        ...

    async def list_sessions(
        self, *, step_id: UUID, block_id: str, user_id: UUID | None = None
    ) -> Sequence[AiReviewSessionRecord]:
        """Sessions of a block (of one user when given), newest first."""
        ...

    async def messages(self, session_id: UUID) -> Sequence[AiReviewMessageRecord]:
        """Messages of a session in order."""
        ...

    async def append(
        self,
        session_id: UUID,
        messages: Sequence[NewAiReviewMessage],
        *,
        status: AiReviewStatus | None = None,
        add_submission: bool = False,
    ) -> list[AiReviewMessageRecord]:
        """Append messages and update the session in one transaction.

        Raises AiReviewClosedError when the session was reviewed meanwhile.
        """
        ...

    async def reserve_submission(
        self, session_id: UUID, *, max_submissions: int
    ) -> AiReviewSessionRecord:
        """Spend one submission of the student for the block, before the model call.

        Locks every session of the student for the step and block, so concurrent
        submits are serialised. Raises AiReviewClosedError for a reviewed session
        and AiReviewNoSubmissionsLeftError once the limit is reached.
        """
        ...

    async def refund_submission(self, session_id: UUID) -> None:
        """Give back a submission reserved for a model call that failed."""
        ...

    async def list_for_user(
        self, user_id: UUID, *, course_id: UUID | None = None, limit: int
    ) -> Sequence[AiReviewSessionRecord]:
        """The user's sessions with at least one submission, newest first."""
        ...
