"""Use case: a student sees and stops the media links issued for them (MCP-B5)."""

from uuid import UUID

from app.modules.lms.application.learning.types import UowFactory
from app.modules.lms.domain.learning.errors import MediaNotAvailableError
from app.modules.lms.domain.learning.media_grant import MediaGrant
from app.shared.actor import Actor
from app.shared.clock import Clock


class RevokeMediaGrants:
    """Only the issuer lists or revokes; someone else's grant looks missing."""

    def __init__(self, uow_factory: UowFactory, clock: Clock) -> None:
        """Store collaborators."""
        self.uow_factory = uow_factory
        self.clock = clock

    async def list_mine(self, actor: Actor) -> list[MediaGrant]:
        """Return the actor's grants, newest first."""
        async with self.uow_factory() as uow:
            return await uow.media_grants.list_for_user(actor.user_id)

    async def revoke(self, actor: Actor, grant_id: UUID) -> None:
        """Stop one grant at once."""
        async with self.uow_factory() as uow:
            done = await uow.media_grants.revoke_if_issued_to(
                grant_id, actor.user_id, self.clock.now()
            )
            if not done:
                raise MediaNotAvailableError()
            await uow.commit()
