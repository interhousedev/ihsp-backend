"""EMIS materials stored as files: attach them to lessons, or purge them (ACA-9)."""

from collections.abc import Sequence
from uuid import UUID

from app.modules.links.application.room_cache_invalidator import RoomCacheInvalidator
from app.modules.links.application.slug_allocator import SlugAllocator
from app.modules.links.domain.link import LessonRole, Link, LinkKind
from app.modules.links.ports.unit_of_work import LinksUnitOfWork, UowFactory
from app.shared.clock import Clock
from app.shared.contracts.links import EMIS_AUTHOR_ID, ImportedFile
from app.shared.ids import new_id


class ImportLessonFiles:
    """One file resource per new (lesson, source URL), authored by EMIS.

    The file's name is the title; ``source_url`` keeps the EMIS address, so a re-sync
    skips it like an imported URL.
    """

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        allocator: SlugAllocator,
        invalidator: RoomCacheInvalidator,
        clock: Clock,
    ) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
        self.allocator = allocator
        self.invalidator = invalidator
        self.clock = clock

    async def execute(self, files: Sequence[ImportedFile]) -> int:
        """Return how many file resources were created."""
        if not files:
            return 0
        created: list[Link] = []
        async with self.uow_factory() as uow:
            known = await uow.links.lesson_urls_of_owner(
                EMIS_AUTHOR_ID, list({item.lesson_id for item in files})
            )
            for item in files:
                key = (item.lesson_id, item.source_url)
                if key in known:
                    continue
                known.add(key)
                created.append(await self._add(uow, item))
            await uow.commit()
        for lesson_id in dict.fromkeys(link.lesson_id for link in created):
            if lesson_id is not None:
                await self.invalidator.lesson_id(lesson_id)
        return len(created)

    async def _add(self, uow: LinksUnitOfWork, item: ImportedFile) -> Link:
        now = self.clock.now()

        def build(slug: str) -> Link:
            return Link(
                id=new_id(),
                slug=slug,
                kind=LinkKind.FILE,
                owner_id=EMIS_AUTHOR_ID,
                created_at=now,
                file_id=item.file_id,
                source_url=item.source_url,
                lesson_id=item.lesson_id,
                lesson_role=LessonRole.MATERIAL,
            )

        return await self.allocator.add(uow, build, kind=LinkKind.FILE)


class PurgeEmisResources:
    """Delete the EMIS-authored resources of lessons for good (admin re-sync)."""

    def __init__(
        self, *, uow_factory: UowFactory, invalidator: RoomCacheInvalidator
    ) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
        self.invalidator = invalidator

    async def execute(self, lesson_ids: Sequence[UUID]) -> list[UUID]:
        """Return the file ids the deleted resources pointed to."""
        if not lesson_ids:
            return []
        async with self.uow_factory() as uow:
            gone = await uow.links.delete_owned_on_lessons(
                EMIS_AUTHOR_ID, list(lesson_ids)
            )
            await uow.commit()
        for lesson_id in dict.fromkeys(link.lesson_id for link in gone):
            if lesson_id is not None:
                await self.invalidator.lesson_id(lesson_id)
        return [link.file_id for link in gone if link.file_id is not None]
