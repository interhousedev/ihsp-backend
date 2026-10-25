"""Delete a short link (SL-7)."""

from uuid import UUID

from app.modules.links.application.revoke_link import RevokeLink
from app.shared.actor import Actor


class DeleteLink:
    """Delete a link of the caller; its ID is not reused for 90 days."""

    def __init__(self, *, revoke_link: RevokeLink) -> None:
        """Initialize the use case."""
        self.revoke_link = revoke_link

    async def execute(self, actor: Actor, link_id: UUID) -> None:
        """Revoke the link and forget the result."""
        await self.revoke_link.execute(actor, link_id)
