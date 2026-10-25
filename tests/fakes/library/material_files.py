"""FilesApi fake for the materials area: image combining, deletion, uploads by size."""

import dataclasses
from collections.abc import Sequence
from uuid import UUID

from app.shared.base_error import ValidationFailedError
from app.shared.contracts.files import FilePurpose, FileRef, FileScope
from tests.fakes.library.files import FakeFilesApi

PDF = "application/pdf"
PNG = "image/png"
JPEG = "image/jpeg"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"


class MaterialFilesApi(FakeFilesApi):
    """`FakeFilesApi` plus `combine_images_to_pdf` and `delete_file`."""

    def __init__(self) -> None:
        """Start empty; `deleted` lists the ids passed to `delete_file`."""
        super().__init__()
        self.deleted: list[UUID] = []
        self.combined: list[tuple[UUID, ...]] = []

    def upload(
        self,
        owner_id: UUID,
        *,
        name: str = "notes.pdf",
        content_type: str = PDF,
        byte_size: int = 1000,
        pages: int = 3,
        purpose: FilePurpose = FilePurpose.LIBRARY_MATERIAL,
    ) -> UUID:
        """A ready upload of the owner with `pages` pages and a given size."""
        file_id = self.add_file(
            owner_id=owner_id,
            name=name,
            content_type=content_type,
            pages=[f"page {i}" for i in range(1, pages + 1)] if pages else (),
            scope=FileScope.LIBRARY,
            purpose=purpose,
        )
        stored = self.files[file_id]
        stored.ref = dataclasses.replace(stored.ref, byte_size=byte_size)
        return file_id

    async def combine_images_to_pdf(
        self,
        file_ids: Sequence[UUID],
        *,
        owner_id: UUID,
        scope: FileScope,
        purpose: FilePurpose,
        name: str,
    ) -> FileRef:
        """One PDF with a page per image; the images stay where they are."""
        if not 1 <= len(file_ids) <= 20:
            raise ValidationFailedError(support_details="1 to 20 images")
        self.combined.append(tuple(file_ids))
        size = sum(self.files[fid].ref.byte_size for fid in file_ids)
        new_id = self.upload(
            owner_id,
            name=name,
            content_type=PDF,
            byte_size=size,
            pages=len(file_ids),
            purpose=purpose,
        )
        return self.files[new_id].ref

    async def delete_file(self, file_id: UUID) -> None:
        """Forget the file; unknown ids are fine."""
        self.deleted.append(file_id)
        self.files.pop(file_id, None)
