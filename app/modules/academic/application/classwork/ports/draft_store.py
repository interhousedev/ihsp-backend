"""Port: the server-side attendance draft of the bot prompt (BOT-16)."""

from dataclasses import dataclass, field
from typing import Protocol
from uuid import UUID


@dataclass(slots=True)
class AttendanceDraft:
    """Toggled absent students and the version the draft started from."""

    base_version: int
    absent: list[UUID] = field(default_factory=list)


class AttendanceDraftStore(Protocol):
    """Drafts live until the end of the lesson's day."""

    async def load(self, lesson_id: UUID) -> AttendanceDraft | None:
        """Return the draft or None."""
        ...

    async def save(
        self, lesson_id: UUID, draft: AttendanceDraft, ttl_seconds: int
    ) -> None:
        """Store the draft for ``ttl_seconds`` seconds."""
        ...

    async def delete(self, lesson_id: UUID) -> None:
        """Forget the draft."""
        ...
