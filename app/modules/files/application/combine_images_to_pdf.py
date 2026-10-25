"""Put the photos a user uploaded into one PDF (a page per photo)."""

import asyncio
from collections.abc import Sequence
from uuid import UUID

from app.modules.files.application.store_bytes import StoreBytes
from app.modules.files.domain.errors import (
    FileDeletedError,
    FileNotReadyError,
    ImageCountError,
    ImageNotSupportedError,
    StoredFileNotFoundError,
)
from app.modules.files.domain.policy import (
    FilesLimits,
    check_size,
    extension_of,
    normalize_name,
)
from app.modules.files.domain.status import FileStatus
from app.modules.files.domain.stored_file import StoredFile
from app.modules.files.ports.image_pdf import ImagePdfBuilder
from app.modules.files.ports.storage import ObjectStorage
from app.modules.files.ports.unit_of_work import UowFactory
from app.shared.contracts.files import FilePurpose, FileScope

MAX_IMAGES = 20
IMAGE_TYPES = frozenset({"image/jpeg", "image/png"})
_READY = frozenset({FileStatus.PROCESSING, FileStatus.READY})


class CombineImagesToPdf:
    """Read the owner's uploaded images in order and store one PDF."""

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        storage: ObjectStorage,
        store: StoreBytes,
        builder: ImagePdfBuilder,
        limits: FilesLimits,
    ) -> None:
        """Store the dependencies."""
        self._uow_factory = uow_factory
        self._storage = storage
        self._store = store
        self._builder = builder
        self._limits = limits

    async def execute(
        self,
        file_ids: Sequence[UUID],
        *,
        owner_id: UUID,
        scope: FileScope,
        purpose: FilePurpose,
        name: str,
    ) -> StoredFile:
        """Return the new PDF file; the images stay as they are.

        Raises:
            ImageCountError: There are no images, or more than 20.
            StoredFileNotFoundError: An id is unknown or belongs to someone else.
            FileDeletedError: An image was deleted.
            FileNotReadyError: An image was not uploaded (or was rejected).
            ImageNotSupportedError: A file is not a plain JPEG or PNG.
            FileTooLargeError: The images together exceed the scope's file limit.
        """
        if not 1 <= len(file_ids) <= MAX_IMAGES:
            raise ImageCountError(params={"max": MAX_IMAGES})
        files = await self._load(file_ids, owner_id)
        check_size(
            sum(file.byte_size for file in files), self._limits.max_bytes_for(scope)
        )
        images = [await self._storage.get(file.key) for file in files]
        pdf = await asyncio.to_thread(self._builder.build, images)
        return await self._store.execute(
            owner_id=owner_id,
            scope=scope,
            purpose=purpose,
            name=_pdf_name(name),
            data=pdf,
        )

    async def _load(self, file_ids: Sequence[UUID], owner_id: UUID) -> list[StoredFile]:
        """The owner's image files in the order of the ids, checked."""
        async with self._uow_factory() as uow:
            rows = {file.id: file for file in await uow.files.get_many(list(file_ids))}
        files: list[StoredFile] = []
        for file_id in file_ids:
            file = rows.get(file_id)
            if file is None or not file.is_owned_by(owner_id):
                raise StoredFileNotFoundError()
            if file.status == FileStatus.DELETED:
                raise FileDeletedError()
            if file.status not in _READY:
                raise FileNotReadyError(params={"status": file.status.value})
            if file.content_type not in IMAGE_TYPES:
                raise ImageNotSupportedError(support_details=file.content_type)
            files.append(file)
        return files


def _pdf_name(name: str) -> str:
    """The display name of the PDF, always ending in ``.pdf``."""
    clean = normalize_name(name)
    return clean if extension_of(clean) == ".pdf" else clean + ".pdf"
