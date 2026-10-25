"""Port: freeze a step draft as a preview revision (authoring side implements it)."""

from typing import Protocol
from uuid import UUID

from app.shared.actor import Actor


class PreviewRevisions(Protocol):
    """Gives staff preview attempts an immutable revision to point at (LMS-8)."""

    async def ensure_preview_revision(self, step_id: UUID, actor: Actor) -> UUID:
        """Freeze the current draft of the step and return the revision id."""
        ...
