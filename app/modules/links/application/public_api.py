"""LinksApi: what other modules may call (contract app.shared.contracts.links)."""

from collections.abc import Sequence
from typing import Literal
from uuid import UUID

from app.modules.links.application.add_lesson_resources import AddLessonResources
from app.modules.links.application.import_lesson_files import (
    ImportLessonFiles,
    PurgeEmisResources,
)
from app.modules.links.application.import_lesson_urls import ImportLessonUrls
from app.modules.links.application.resource_builder import ResourceBuilder
from app.modules.links.application.resource_refs import to_ref
from app.modules.links.domain.errors import InvalidLinkTargetError
from app.modules.links.domain.link import SHARE_KINDS, LessonRole, LinkKind, LinkState
from app.modules.links.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from app.shared.clock import Clock
from app.shared.contracts.links import (
    EMIS_AUTHOR_ID,
    ImportedFile,
    ImportedUrl,
    ResourceRef,
)


class LinksApiImpl:
    """Implements LinksApi for schedule, notify, bot and ai consumers."""

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        builder: ResourceBuilder,
        add_resources: AddLessonResources,
        import_urls: ImportLessonUrls,
        import_files: ImportLessonFiles,
        purge_emis: PurgeEmisResources,
        clock: Clock,
    ) -> None:
        """Store the collaborators."""
        self.import_files = import_files
        self.purge_emis = purge_emis
        self.uow_factory = uow_factory
        self.builder = builder
        self.add_resources = add_resources
        self.import_urls = import_urls
        self.clock = clock

    async def lesson_resources(
        self, lesson_id: UUID, *, include_hidden: bool = False
    ) -> list[ResourceRef]:
        """Return the lesson's resources as ResourceRef objects."""
        found = await self.resources_for_lessons(
            [lesson_id], include_hidden=include_hidden
        )
        return found.get(lesson_id, [])

    async def resources_for_lessons(
        self, lesson_ids: Sequence[UUID], *, include_hidden: bool = False
    ) -> dict[UUID, list[ResourceRef]]:
        """Return visible resources grouped by lesson; materials come first."""
        if not lesson_ids:
            return {}
        async with self.uow_factory() as uow:
            links = await uow.links.list_for_lessons(list(lesson_ids))
        listed = [
            link
            for link in links
            if link.is_listed_resource(include_hidden=include_hidden)
        ]
        views = await self.builder.resources(listed)
        grouped: dict[UUID, list[ResourceRef]] = {}
        for view in sorted(
            views, key=lambda v: v.link.lesson_role is not LessonRole.MATERIAL
        ):
            ref = to_ref(view)
            grouped.setdefault(ref.lesson_id, []).append(ref)
        return grouped

    async def add_lesson_resource(
        self,
        actor: Actor,
        lesson_id: UUID,
        *,
        role: Literal["material", "attachment"],
        url: str | None = None,
        file_id: UUID | None = None,
    ) -> ResourceRef:
        """Attach a URL or the actor's file to one lesson."""
        if (url is None) == (file_id is None):
            raise InvalidLinkTargetError(params={"role": role})
        views = await self.add_resources.execute(
            actor,
            lesson_id,
            role=LessonRole(role),
            kind=LinkKind.URL if url is not None else LinkKind.FILE,
            target_url=url,
            file_id=file_id,
        )
        return to_ref(views[0])

    async def import_lesson_urls(self, urls: Sequence[ImportedUrl]) -> int:
        """Attach URLs from EMIS as materials (author "EMIS"); return the new ones."""
        return await self.import_urls.execute(urls)

    async def emis_sources(self, lesson_ids: Sequence[UUID]) -> set[tuple[UUID, str]]:
        """Return (lesson id, URL) of everything EMIS ever attached, deleted too."""
        async with self.uow_factory() as uow:
            return await uow.links.lesson_urls_of_owner(
                EMIS_AUTHOR_ID, list(lesson_ids)
            )

    async def import_lesson_files(self, files: Sequence[ImportedFile]) -> int:
        """Attach stored EMIS materials as file resources; return the new ones."""
        return await self.import_files.execute(files)

    async def purge_emis_resources(self, lesson_ids: Sequence[UUID]) -> list[UUID]:
        """Delete the lessons' EMIS resources for good; return their file ids."""
        return await self.purge_emis.execute(lesson_ids)

    async def used_by_files(
        self, file_ids: Sequence[UUID]
    ) -> dict[UUID, list[tuple[str, UUID, str]]]:
        """Return (kind, id, label) per file: "lesson" resources and "link"s."""
        async with self.uow_factory() as uow:
            links = await uow.links.active_by_files(list(file_ids))
        used: dict[UUID, list[tuple[str, UUID, str]]] = {}
        for link in links:
            if link.file_id is None:
                continue
            label = link.title or link.slug
            if link.lesson_id is not None:
                item = ("lesson", link.lesson_id, label)
            else:
                item = ("link", link.id, label)
            used.setdefault(link.file_id, []).append(item)
        return used

    async def is_shared(self, chat_id: UUID) -> bool:
        """True if the chat has a live share link (for ChatDetail.shared)."""
        now = self.clock.now()
        async with self.uow_factory() as uow:
            links = await uow.links.active_by_target(LinkKind.CHAT, chat_id)
        return any(link.state(now) is LinkState.ACTIVE for link in links)

    async def resolve_share(self, slug: str) -> tuple[str, UUID] | None:
        """Return (kind, target_id) of an active share, else None."""
        async with self.uow_factory() as uow:
            link = await uow.links.get_by_slug(slug)
        if link is None or link.kind not in SHARE_KINDS or link.target_id is None:
            return None
        if link.state(self.clock.now()) is not LinkState.ACTIVE:
            return None
        return link.kind.value, link.target_id
