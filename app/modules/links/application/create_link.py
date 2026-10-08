"""Create a short link to a URL or a file (SL-1, SL-3)."""

from uuid import UUID

from app.modules.links.application.link_creation_limit import LinkCreationLimit
from app.modules.links.application.link_urls import LinkUrls
from app.modules.links.application.slug_allocator import SlugAllocator
from app.modules.links.application.target_resolver import TargetResolver
from app.modules.links.application.views import LinkView
from app.modules.links.domain.link import Link, LinkKind
from app.modules.links.ports.unit_of_work import UowFactory
from app.shared.actor import Actor, Role
from app.shared.base_error import ForbiddenError
from app.shared.clock import Clock
from app.shared.ids import new_id


class CreateLink:
    """Shorten a URL (3+ random characters) or publish a file (8+) (SL-2, SL-3)."""

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        resolver: TargetResolver,
        allocator: SlugAllocator,
        limit: LinkCreationLimit,
        clock: Clock,
        urls: LinkUrls,
    ) -> None:
        """Initialize the use case."""
        self.uow_factory = uow_factory
        self.resolver = resolver
        self.allocator = allocator
        self.limit = limit
        self.clock = clock
        self.urls = urls

    async def execute(
        self,
        actor: Actor,
        *,
        kind: LinkKind,
        target_url: str | None = None,
        file_id: UUID | None = None,
        requested_length: int | None = None,
    ) -> LinkView:
        """Check the target, pick a free slug and save the link."""
        is_admin = actor.has(Role.ADMIN)
        if requested_length is not None and not is_admin:
            raise ForbiddenError(support_details="only Administration picks length")
        await self.limit.hit(actor.user_id)
        target = await self.resolver.resolve(
            actor, kind=kind, target_url=target_url, file_id=file_id
        )
        now = self.clock.now()

        def build(slug: str) -> Link:
            return Link(
                id=new_id(),
                slug=slug,
                kind=target.kind,
                owner_id=actor.user_id,
                created_at=now,
                target_url=target.target_url,
                file_id=target.file_id,
                title=target.title,
            )

        async with self.uow_factory() as uow:
            link = await self.allocator.add(
                uow,
                build,
                kind=target.kind,
                is_admin=is_admin,
                requested_length=requested_length,
            )
            await uow.commit()
        return LinkView(link=link, url=self.urls.url_for(link), file=target.file)
