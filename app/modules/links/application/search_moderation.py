"""Search links for moderation by slug, URL or owner (UF-ADM-10)."""

from uuid import UUID

from app.modules.links.application.moderation_views import ModerationViews
from app.modules.links.application.views import ModerationView
from app.modules.links.domain.link import Link
from app.modules.links.domain.search_query import extract_slug
from app.modules.links.ports.unit_of_work import UowFactory
from app.shared.actor import Actor, Role
from app.shared.contracts.identity import IdentityDirectory

SEARCH_USERS = 10
SEARCH_LINKS = 50


class SearchModeration:
    """Find links by short ID, share or short URL, or by the owner's name or login."""

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        views: ModerationViews,
        identity: IdentityDirectory,
    ) -> None:
        """Initialize the use case."""
        self.uow_factory = uow_factory
        self.views = views
        self.identity = identity

    async def execute(self, actor: Actor, query: str) -> list[ModerationView]:
        """Return matching links, the exact slug match first."""
        actor.require(Role.ADMIN)
        text = query.strip()
        if not text:
            return []
        found: dict[UUID, Link] = {}
        async with self.uow_factory() as uow:
            by_slug = await uow.links.get_by_slug(extract_slug(text))
            if by_slug is not None:
                found[by_slug.id] = by_slug
            users = await self.identity.search_users(text, limit=SEARCH_USERS)
            owners = [user.id for user in users]
            if owners:
                for link in await uow.links.list_by_owners(owners, SEARCH_LINKS):
                    found.setdefault(link.id, link)
        return await self.views.build(list(found.values()))
