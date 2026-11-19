"""Port: essay review links and the feedback left on an essay."""

from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.modules.admission.domain.essay_invites import EssayInvite, Feedback


class EssayInviteRepository(Protocol):
    """Review links; the label is sealed, the token kept as a hash only."""

    async def add(self, invite: EssayInvite) -> EssayInvite:
        """Store a new link."""
        ...

    async def get(self, invite_id: UUID) -> EssayInvite | None:
        """Return a link by id."""
        ...

    async def by_token_hash(self, digest: str) -> EssayInvite | None:
        """Return the link of a token hash, whatever its state."""
        ...

    async def list_for_essay(self, essay_id: UUID) -> list[EssayInvite]:
        """Return every link of an essay, newest first."""
        ...

    async def count_active(self, essay_id: UUID, now: datetime) -> int:
        """Count the links of an essay that are neither revoked nor expired."""
        ...

    async def revoke(self, invite_id: UUID, now: datetime) -> None:
        """Stamp a link as revoked (idempotent)."""
        ...

    async def touch(self, invite_id: UUID, now: datetime) -> None:
        """Record when a link was last opened."""
        ...


class EssayFeedbackRepository(Protocol):
    """Feedback rows; quote, body and author name are sealed."""

    async def add(self, item: Feedback) -> Feedback:
        """Store a comment."""
        ...

    async def get(self, feedback_id: UUID) -> Feedback | None:
        """Return a comment by id."""
        ...

    async def list_for_essay(self, essay_id: UUID) -> list[Feedback]:
        """Return every comment of an essay, oldest first."""
        ...

    async def list_for_invite(self, invite_id: UUID) -> list[Feedback]:
        """Return the comments left through one link, oldest first."""
        ...

    async def set_resolved(self, feedback_id: UUID, at: datetime | None) -> None:
        """Mark a comment resolved at `at`, or open again with None."""
        ...

    async def delete(self, feedback_id: UUID) -> None:
        """Delete a comment with its replies."""
        ...
