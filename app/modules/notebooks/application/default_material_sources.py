"""The source a student's subject notebook gets for a default material."""

from dataclasses import replace
from uuid import UUID

from app.modules.notebooks.application.readers.base import ResolvedSource, clean_title
from app.modules.notebooks.application.readers.file_reader import require_text
from app.modules.notebooks.application.readers.registry import SourceReaders
from app.modules.notebooks.domain.default_materials import (
    DEFAULT_MARK,
    DefaultMaterial,
    DefaultMaterialKind,
)
from app.modules.notebooks.domain.enums import SourceKind
from app.modules.notebooks.domain.source_input import LibraryItemInput, UrlInput
from app.shared.base_error import BaseError
from app.shared.contracts.files import FilesApi


class DefaultMaterialSources:
    """Reads a default material for one student, the same way as their own sources.

    A file is read as the admin's upload (its text, no owner check: the student may
    only see what the admin put in). A link and a library item go through the readers
    of the student's own sources, so the same access and size rules apply. None while
    the material cannot be read (not ready, no text, no access): the next sync tries
    again.
    """

    def __init__(self, *, readers: SourceReaders, files: FilesApi | None) -> None:
        """Store the readers and the files API (None: file materials are skipped)."""
        self.readers = readers
        self.files = files

    async def resolve(
        self, owner_id: UUID, material: DefaultMaterial
    ) -> ResolvedSource | None:
        """The source of the material for the student, marked as its copy."""
        try:
            resolved = await self._resolve(owner_id, material)
        except (BaseError, ValueError):
            return None  # not readable now: picked up by a later sync
        if resolved is None:
            return None
        origin = {**(resolved.origin or {}), DEFAULT_MARK: str(material.id)}
        return replace(resolved, origin=origin)

    async def _resolve(
        self, owner_id: UUID, material: DefaultMaterial
    ) -> ResolvedSource | None:
        if material.kind is DefaultMaterialKind.FILE:
            return await self._file(material)
        if material.kind is DefaultMaterialKind.LINK:
            return await self.readers.url_reader.resolve(
                owner_id, UrlInput(url=material.url or "", title=material.title)
            )
        reader = self.readers.library_reader
        if reader is None or material.library_item_id is None:
            return None
        return await reader.resolve(
            owner_id, LibraryItemInput(item_id=material.library_item_id)
        )

    async def _file(self, material: DefaultMaterial) -> ResolvedSource | None:
        if self.files is None or material.file_id is None:
            return None
        ref = await self.files.get(material.file_id)
        if ref is None or ref.status == "deleted":
            return None
        require_text(ref)  # raises while the file is not ready or has no text
        return ResolvedSource(
            kind=SourceKind.FILE,
            title=clean_title(material.title, "File"),
            ref={"file_id": str(ref.id), "content_type": ref.content_type},
            ref_key=f"file:{ref.id}",
        )
