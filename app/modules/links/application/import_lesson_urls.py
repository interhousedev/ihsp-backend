"""Attach web addresses from EMIS to lessons as materials (author "EMIS")."""

from collections.abc import Sequence

from app.modules.links.application.room_cache_invalidator import RoomCacheInvalidator
from app.modules.links.application.slug_allocator import SlugAllocator
from app.modules.links.domain.errors import BlockedUrlError
from app.modules.links.domain.link import LessonRole, Link, LinkKind
from app.modules.links.domain.url_policy import UrlPolicy
from app.modules.links.ports.unit_of_work import LinksUnitOfWork, UowFactory
from app.shared.clock import Clock
from app.shared.contracts.links import EMIS_AUTHOR_ID, ImportedUrl
from app.shared.ids import new_id

import structlog

log = structlog.get_logger(__name__)


class ImportLessonUrls:
    """Create one material link per new (lesson, URL); no user acts, so no rate limit.

    The title comes from EMIS (no page is fetched). Skipping a URL that EMIS already
    attached, even one a teacher later deleted, keeps the daily re-sync idempotent.
    """

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        policy: UrlPolicy,
        allocator: SlugAllocator,
        invalidator: RoomCacheInvalidator,
        clock: Clock,
    ) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
        self.policy = policy
        self.allocator = allocator
        self.invalidator = invalidator
        self.clock = clock

    async def execute(self, urls: Sequence[ImportedUrl]) -> int:
        """Return how many links were created."""
        wanted = self._checked(urls)
        if not wanted:
            return 0
        created: list[Link] = []
        async with self.uow_factory() as uow:
            known = await uow.links.lesson_urls_of_owner(
                EMIS_AUTHOR_ID, list({item.lesson_id for item, _ in wanted})
            )
            for item, url in wanted:
                if (item.lesson_id, url) in known:
                    continue
                known.add((item.lesson_id, url))
                created.append(await self._add(uow, item, url))
            await uow.commit()
        for lesson_id in dict.fromkeys(link.lesson_id for link in created):
            if lesson_id is not None:
                await self.invalidator.lesson_id(lesson_id)
        return len(created)

    def _checked(self, urls: Sequence[ImportedUrl]) -> list[tuple[ImportedUrl, str]]:
        checked: list[tuple[ImportedUrl, str]] = []
        for item in urls:
            try:
                checked.append((item, self.policy.check(item.url).url))
            except BlockedUrlError:
                log.warning("emis_url_blocked", lesson_id=str(item.lesson_id))
        return checked

    async def _add(self, uow: LinksUnitOfWork, item: ImportedUrl, url: str) -> Link:
        now = self.clock.now()

        def build(slug: str) -> Link:
            return Link(
                id=new_id(),
                slug=slug,
                kind=LinkKind.URL,
                owner_id=EMIS_AUTHOR_ID,
                created_at=now,
                target_url=url,
                title=item.title.strip()[:200] or None,
                lesson_id=item.lesson_id,
                lesson_role=LessonRole.MATERIAL,
            )

        return await self.allocator.add(uow, build, kind=LinkKind.URL)
