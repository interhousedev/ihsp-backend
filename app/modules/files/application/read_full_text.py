"""Read the whole extracted text of a file with the offsets of its pages."""

from typing import Any
from uuid import UUID

from app.modules.files.domain.errors import (
    FileDeletedError,
    NoTextError,
    StoredFileNotFoundError,
)
from app.modules.files.domain.status import FileStatus
from app.modules.files.ports.storage import ObjectStorage
from app.modules.files.ports.unit_of_work import UowFactory
from app.shared.contracts.files import FullText


class ReadFullText:
    """The text sidecar in one piece, for modules that chunk it themselves."""

    def __init__(self, *, uow_factory: UowFactory, storage: ObjectStorage) -> None:
        """Store the dependencies."""
        self._uow_factory = uow_factory
        self._storage = storage

    async def execute(self, file_id: UUID) -> FullText:
        """Return the text and ``page_starts`` (empty for files without offsets).

        Raises:
            StoredFileNotFoundError: The file does not exist.
            FileDeletedError: The file was deleted.
            NoTextError: The file has no extracted text.
        """
        async with self._uow_factory() as uow:
            file = await uow.files.get(file_id)
        if file is None:
            raise StoredFileNotFoundError()
        if file.status == FileStatus.DELETED:
            raise FileDeletedError()
        if file.text_bytes is None:
            raise NoTextError()
        text = (await self._storage.get(file.text_key)).decode()
        return FullText(
            file_id=file_id, text=text, page_starts=_page_starts(file.metadata, text)
        )


def _page_starts(metadata: dict[str, Any], text: str) -> tuple[int, ...]:
    """Return the stored page offsets, or () when absent or not usable."""
    raw = metadata.get("page_starts")
    if not isinstance(raw, list):
        return ()
    if not all(isinstance(v, int) and 0 <= v <= len(text) for v in raw):
        return ()
    return tuple(raw)
