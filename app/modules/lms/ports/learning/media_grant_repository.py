"""Port: media grants."""

from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.modules.lms.domain.learning.media_grant import MediaGrant


class MediaGrantRepository(Protocol):
    """The links a user holds to media of courses."""

    async def rotate(
        self,
        *,
        token_hash: str,
        course_id: UUID,
        step_id: UUID,
        block_id: str,
        file_id: UUID,
        issued_to: UUID,
        connector_id: UUID | None,
        expires_at: datetime,
    ) -> MediaGrant:
        """Create the grant of (user, step, block) or replace it, killing its token."""
        ...

    async def get_by_hash(self, token_hash: str) -> MediaGrant | None:
        """Return the grant of a token."""
        ...

    async def add_redeem(self, grant_id: UUID) -> None:
        """Count one redeem."""
        ...

    async def revoke(self, grant_id: UUID, now: datetime) -> None:
        """Stop a grant."""
        ...

    async def revoke_if_issued_to(
        self, grant_id: UUID, user_id: UUID, now: datetime
    ) -> bool:
        """Stop a grant of this user; False when it is not theirs or is missing."""
        ...

    async def list_for_user(self, user_id: UUID) -> list[MediaGrant]:
        """Return the user's grants, newest first."""
        ...
