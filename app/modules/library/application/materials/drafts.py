"""Builds a draft material and stores its text body; shared by create and version."""

from collections.abc import Sequence
from dataclasses import replace
from functools import partial
from uuid import UUID

from app.modules.library.application.materials.attribution import attribute
from app.modules.library.application.materials.inputs import MaterialData
from app.modules.library.application.materials.limits import max_file_bytes
from app.modules.library.application.materials.search_text import build_search_text
from app.modules.library.application.materials.upload_guard import UploadGuard
from app.modules.library.domain.entities import (
    Item,
    ItemFile,
    MaterialDetails,
    SubjectLink,
    TopicLink,
)
from app.modules.library.domain.enums import (
    EventKind,
    FileFormat,
    ItemKind,
    ItemStatus,
    TextStatus,
)
from app.modules.library.domain.errors import FileTooLargeError
from app.modules.library.domain.material_flow import uploader_role_of, visibility_for
from app.modules.library.domain.slugs import make_slug
from app.modules.library.ports.directories import AcademicDirectory
from app.modules.library.ports.unit_of_work import LibraryUnitOfWork
from app.settings import LibrarySettings
from app.shared.actor import Actor, Role
from app.shared.base_error import ValidationFailedError
from app.shared.clock import Clock
from app.shared.contracts.files import FilePurpose, FilesApi, FileScope
from app.shared.contracts.identity import IdentityDirectory
from app.shared.ids import new_id
from app.shared.tasks import TaskKicker

TITLE_MAX = 255
DESCRIPTION_MAX = 2000
PROCESS_TASK = "library.process_item_file"
BYTES_PER_MB = 1024 * 1024


def checked(data: MaterialData) -> MaterialData:
    """The input with trimmed text; refuses what the form should have stopped."""
    title = data.title.strip()
    description = data.description.strip()
    if not title or len(title) > TITLE_MAX:
        raise ValidationFailedError(params={"field": "title"})
    if len(description) > DESCRIPTION_MAX:
        raise ValidationFailedError(params={"field": "description"})
    return replace(
        data,
        title=title,
        description=description,
        years_of_study=tuple(sorted(set(data.years_of_study))),
    )


def too_large(limit: int) -> FileTooLargeError:
    """`library/file-too-large` with the limit in megabytes for the message."""
    return FileTooLargeError(
        params={"max_mb": limit // BYTES_PER_MB, "limit": limit, "max": limit}
    )


class MaterialDrafts:
    """Creates drafts and keeps the markdown body of a material."""

    def __init__(
        self,
        *,
        clock: Clock,
        files: FilesApi,
        identity: IdentityDirectory,
        academic: AcademicDirectory,
        kicker: TaskKicker,
        guard: UploadGuard,
        settings: LibrarySettings,
    ) -> None:
        """Store the collaborators."""
        self.clock = clock
        self.files = files
        self.identity = identity
        self.academic = academic
        self.kicker = kicker
        self.guard = guard
        self.settings = settings

    async def build(
        self,
        uow: LibraryUnitOfWork,
        actor: Actor,
        data: MaterialData,
        *,
        supersedes_id: UUID | None = None,
    ) -> Item:
        """Store a new draft of the actor with its tags, history and optional body."""
        data = checked(data)
        await self.guard.ensure_not_banned(uow, actor.user_id)
        await self._check_subjects(data.subject_ids)
        await self.check_topics(uow, data.topic_ids)
        item = await self._item(actor, data, supersedes_id)
        await uow.items.add(item)
        await uow.items.set_subject_links(
            item.id, [SubjectLink(subject_id) for subject_id in data.subject_ids]
        )
        await self.set_topics(uow, item.id, data.topic_ids)
        kind = EventKind.VERSION_ADDED if supersedes_id else EventKind.CREATED
        data_log = {"supersedes": str(supersedes_id)} if supersedes_id else {}
        await uow.events.append(
            item.id, kind, at=item.created_at, actor_id=actor.user_id, data=data_log
        )
        if data.body_md:
            await self.set_body(uow, item, data.body_md)
        return item

    async def _item(
        self, actor: Actor, data: MaterialData, supersedes_id: UUID | None
    ) -> Item:
        now = self.clock.now()
        item_id = new_id()
        who = await attribute(self.identity, self.academic, actor.user_id, actor.roles)
        item = Item(
            id=item_id,
            slug=make_slug(data.title, item_id),
            kind=ItemKind.MATERIAL,
            type=data.type,
            title=data.title,
            language=data.language,
            status=ItemStatus.DRAFT,
            visibility=visibility_for(
                data.licence, is_teacher=Role.TEACHER in actor.roles
            ),
            created_at=now,
            updated_at=now,
            description=data.description or None,
            author_label=who.label,
            years_of_study=list(data.years_of_study),
            download_allowed=True,
            owner_id=actor.user_id,
            created_by=actor.user_id,
            supersedes_id=supersedes_id,
            material=MaterialDetails(
                uploader_id=actor.user_id,
                uploader_role=uploader_role_of(actor.roles),
                uploader_name=who.name,
                uploader_cohort=who.cohort,
                licence=data.licence,
                attested_at=now if data.attested else None,
            ),
        )
        item.search_text = build_search_text(item)
        return item

    async def _check_subjects(self, subject_ids: Sequence[UUID]) -> None:
        if not subject_ids:
            return
        known = await self.academic.subject_names(list(subject_ids), "en")
        if not set(subject_ids) <= set(known):
            raise ValidationFailedError(params={"field": "subject_ids"})

    async def check_topics(
        self, uow: LibraryUnitOfWork, topic_ids: Sequence[UUID]
    ) -> None:
        """Refuse topic ids the taxonomy does not know."""
        if not topic_ids:
            return
        known = await uow.taxonomy.topic_names(list(topic_ids))
        if not set(topic_ids) <= set(known):
            raise ValidationFailedError(params={"field": "topic_ids"})

    async def set_topics(
        self, uow: LibraryUnitOfWork, item_id: UUID, topic_ids: Sequence[UUID]
    ) -> None:
        """Replace the topics of the whole item."""
        await uow.items.set_topic_links(
            item_id,
            [TopicLink(topic_id, position=i) for i, topic_id in enumerate(topic_ids)],
        )

    async def set_body(self, uow: LibraryUnitOfWork, item: Item, body_md: str) -> None:
        """Store the markdown text as the item's `md` file, replacing the old one."""
        assert item.material is not None
        data = body_md.encode()
        role = item.material.uploader_role
        if len(data) > max_file_bytes(role, self.settings):
            raise too_large(max_file_bytes(role, self.settings))
        ref = await self.files.store_bytes(
            owner_id=item.material.uploader_id,
            scope=FileScope.LIBRARY,
            purpose=FilePurpose.LIBRARY_MATERIAL,
            name=f"{item.slug}.md",
            data=data,
        )
        replaced = [f.file_id for f in item.files if f.format is FileFormat.MD]
        for file_id in replaced:
            await uow.items.remove_file(item.id, file_id)
        item.files = [f for f in item.files if f.format is not FileFormat.MD]
        item_file = ItemFile(
            item_id=item.id,
            file_id=ref.id,
            format=FileFormat.MD,
            byte_size=len(data),
            is_primary=not item.files,
            readable=True,
            text_status=TextStatus.READY,
        )
        await uow.items.add_file(item_file)
        item.files.append(item_file)
        item.has_text = True
        await uow.items.save(item)
        self.kick_processing(uow, item.id, ref.id)
        self.delete_after_commit(uow, replaced)

    def kick_processing(
        self, uow: LibraryUnitOfWork, item_id: UUID, file_id: UUID
    ) -> None:
        """Start the scan job for a file once the transaction has committed."""
        uow.after_commit(
            partial(
                self.kicker.kick,
                PROCESS_TASK,
                item_id=str(item_id),
                file_id=str(file_id),
            )
        )

    def delete_after_commit(
        self, uow: LibraryUnitOfWork, file_ids: Sequence[UUID]
    ) -> None:
        """Delete replaced or abandoned files for good once the commit has succeeded."""
        for file_id in file_ids:
            uow.after_commit(partial(self.files.delete_file, file_id))
