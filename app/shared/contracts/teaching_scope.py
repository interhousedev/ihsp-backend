"""Which subjects and groups a teacher currently teaches."""

from typing import Protocol
from uuid import UUID

from app.shared.actor import Actor


class TeachingScope(Protocol):
    """Authorizes a destination for teaching material."""

    async def can_teach(
        self, actor: Actor, subject_id: UUID, group_id: UUID | None
    ) -> bool:
        """True when the actor teaches the subject (and group) now; admins pass."""
        ...
