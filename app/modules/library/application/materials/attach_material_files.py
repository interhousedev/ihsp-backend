"""Attach the uploaded file of a draft material: a PDF, photos, or Office files."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from uuid import UUID

from app.modules.library.application.detail import DetailBuilder, ItemDetailView
from app.modules.library.application.materials.drafts import MaterialDrafts, too_large
from app.modules.library.application.materials.limits import max_file_bytes, max_pages
from app.modules.library.application.materials.loading import load_owned
from app.modules.library.domain.entities import Item, ItemFile
from app.modules.library.domain.enums import (
    EventKind,
    FileFormat,
    ItemStatus,
    TextStatus,
    UploaderRole,
)
from app.modules.library.domain.errors import NotEditableError, TooManyPagesError
from app.modules.library.ports.unit_of_work import LibraryUnitOfWork, UowFactory
from app.settings import LibrarySettings
from app.shared.actor import Actor
from app.shared.base_error import ValidationFailedError
from app.shared.clock import Clock
from app.shared.contracts.files import FilePurpose, FileRef, FilesApi, FileScope

EDITABLE = frozenset({ItemStatus.DRAFT, ItemStatus.CHANGES_REQUESTED})
MAX_PHOTOS = 20
PDF_TYPE = "application/pdf"
PHOTO_TYPES = frozenset({"image/jpeg", "image/png"})
OFFICE_TYPES = {
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": (
        FileFormat.DOCX
    ),
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": (
        FileFormat.PPTX
    ),
}


@dataclass(slots=True)
class _Upload:
    """The uploads of one request sorted by what they are."""

    pdf: FileRef | None = None
    photos: list[FileRef] = field(default_factory=list)
    office: list[FileRef] = field(default_factory=list)


def _bad_files() -> ValidationFailedError:
    return ValidationFailedError(params={"field": "file_ids"})


class AttachMaterialFiles:
    """Replace the uploaded file of a draft; the written text body stays."""

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        clock: Clock,
        files: FilesApi,
        drafts: MaterialDrafts,
        detail: DetailBuilder,
        settings: LibrarySettings,
    ) -> None:
        """Initialize the use case."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.files = files
        self.drafts = drafts
        self.detail = detail
        self.settings = settings

    async def execute(
        self, actor: Actor, item_id: UUID, file_ids: Sequence[UUID], *, locale: str
    ) -> ItemDetailView:
        """Check and store the files, start the scan job and return the detail."""
        async with self.uow_factory() as uow:
            item = await load_owned(uow, item_id, actor, lock=True)
            if item.status not in EDITABLE or item.material is None:
                raise NotEditableError(params={"status": item.status.value})
            role = item.material.uploader_role
            upload = self._sort(await self._owned(actor, file_ids), role)
            main = await self._main(actor, upload)
            await self._store(uow, item, main, upload.office, actor)
            self.drafts.delete_after_commit(uow, [ref.id for ref in upload.photos])
            view = await self.detail.build(uow, item, viewer=actor, locale=locale)
            await uow.commit()
        return view

    async def _owned(self, actor: Actor, file_ids: Sequence[UUID]) -> list[FileRef]:
        """The caller's own ready uploads of purpose `library_material`."""
        if not file_ids or len(set(file_ids)) != len(file_ids):
            raise _bad_files()
        refs = await self.files.get_many(list(file_ids))
        found = [refs.get(file_id) for file_id in file_ids]
        owned = [
            ref
            for ref in found
            if ref is not None
            and ref.owner_id == actor.user_id
            and ref.purpose is FilePurpose.LIBRARY_MATERIAL
            and ref.status == "ready"
        ]
        if len(owned) != len(file_ids):
            raise _bad_files()
        return owned

    def _sort(self, refs: Sequence[FileRef], role: UploaderRole) -> _Upload:
        upload = _Upload()
        for ref in refs:
            self._classify(ref, upload, role)
        if upload.pdf is not None and upload.photos:
            raise _bad_files()
        if len(upload.photos) > MAX_PHOTOS:
            raise TooManyPagesError(params={"max": MAX_PHOTOS, "limit": MAX_PHOTOS})
        self._check_sizes(refs, role)
        return upload

    @staticmethod
    def _classify(ref: FileRef, upload: _Upload, role: UploaderRole) -> None:
        kind = ref.content_type
        if kind == PDF_TYPE and upload.pdf is None:
            upload.pdf = ref
        elif kind in PHOTO_TYPES:
            upload.photos.append(ref)
        elif kind in OFFICE_TYPES and role is not UploaderRole.STUDENT:
            upload.office.append(ref)
        else:
            raise _bad_files()

    def _check_sizes(self, refs: Sequence[FileRef], role: UploaderRole) -> None:
        limit = max_file_bytes(role, self.settings)
        photos = sum(r.byte_size for r in refs if r.content_type in PHOTO_TYPES)
        if photos > limit or any(r.byte_size > limit for r in refs):
            raise too_large(limit)

    async def _main(self, actor: Actor, upload: _Upload) -> FileRef | None:
        """The PDF to read: the uploaded one, or the photos combined."""
        main = upload.pdf
        if upload.photos:
            main = await self.files.combine_images_to_pdf(
                [ref.id for ref in upload.photos],
                owner_id=actor.user_id,
                scope=FileScope.LIBRARY,
                purpose=FilePurpose.LIBRARY_MATERIAL,
                name="photos.pdf",
            )
        if main is None and not upload.office:
            raise _bad_files()
        return main

    async def _store(
        self,
        uow: LibraryUnitOfWork,
        item: Item,
        main: FileRef | None,
        office: Sequence[FileRef],
        actor: Actor,
    ) -> None:
        """Swap the uploaded files of the item for the new ones."""
        assert item.material is not None
        pages = await self._pages(main, item.material.uploader_role)
        old = [f for f in item.files if f.format is not FileFormat.MD]
        kept = [f for f in item.files if f.format is FileFormat.MD]
        for item_file in kept:
            if main is not None and item_file.is_primary:
                item_file.is_primary = False
                await uow.items.save_file(item_file)
        for item_file in old:
            await uow.items.remove_file(item.id, item_file.file_id)
        item.files = kept
        if main is not None:
            await self._add(uow, item, main, FileFormat.PDF, primary=True, pages=pages)
            item.page_count = pages
            self.drafts.kick_processing(uow, item.id, main.id)
        for ref in office:
            fmt = OFFICE_TYPES[ref.content_type]
            await self._add(uow, item, ref, fmt, primary=not item.files)
        item.updated_at = self.clock.now()
        await uow.items.save(item)
        await uow.events.append(
            item.id,
            EventKind.EDITED,
            at=item.updated_at,
            actor_id=actor.user_id,
            data={"files": len(item.files)},
        )
        replaced = [f.file_id for f in old]
        self.drafts.delete_after_commit(uow, replaced)

    async def _pages(self, main: FileRef | None, role: UploaderRole) -> int | None:
        if main is None:
            return None
        pages = await self.files.page_count(main.id)
        limit = max_pages(role, self.settings)
        if pages is not None and limit is not None and pages > limit:
            raise TooManyPagesError(params={"max": limit, "limit": limit})
        return pages

    async def _add(
        self,
        uow: LibraryUnitOfWork,
        item: Item,
        ref: FileRef,
        fmt: FileFormat,
        *,
        primary: bool,
        pages: int | None = None,
    ) -> None:
        readable = fmt is FileFormat.PDF
        item_file = ItemFile(
            item_id=item.id,
            file_id=ref.id,
            format=fmt,
            byte_size=ref.byte_size,
            is_primary=primary,
            pages=pages,
            readable=readable,
            text_status=TextStatus.PENDING if readable else TextStatus.NONE,
        )
        await uow.items.add_file(item_file)
        item.files.append(item_file)
