"""Moderation views: links with their owners."""

from collections.abc import Sequence
from uuid import UUID

from app.modules.links.application.resource_builder import ResourceBuilder
from app.modules.links.application.views import ModerationView, PersonView
from app.modules.links.domain.errors import LinkNotFoundError
from app.modules.links.domain.link import Link
from app.modules.links.ports.unit_of_work import LinksUnitOfWork
from app.shared.contracts.identity import IdentityDirectory


class ModerationViews:
    """Builds ModerationView objects in two batched lookups."""

    def __init__(self, builder: ResourceBuilder, identity: IdentityDirectory) -> None:
        """Store the link view builder and the identity directory."""
        self.builder = builder
        self.identity = identity

    async def build(self, links: Sequence[Link]) -> list[ModerationView]:
        """Return a view per link, in order."""
        link_views = await self.builder.link_views(links)
        owner_ids = list({link.owner_id for link in links})
        users = await self.identity.get_users(owner_ids) if owner_ids else {}
        views = []
        for view in link_views:
            user = users.get(view.link.owner_id)
            owner = (
                PersonView(user.id, user.first_name, user.last_name) if user else None
            )
            views.append(ModerationView(link=view, owner=owner))
        return views


async def load_link(uow: LinksUnitOfWork, link_id: UUID) -> Link:
    """Return the link or raise LinkNotFoundError."""
    link = await uow.links.get(link_id)
    if link is None:
        raise LinkNotFoundError(params={"link_id": str(link_id)})
    return link
