"""FilesApi for the scan job tests: outlines, text without offsets, failures."""

from uuid import UUID

from app.shared.base_error import NotFoundError, ValidationFailedError
from app.shared.contracts.files import FileRef, FullText, OutlineEntry
from tests.fakes.library.files import FakeFilesApi


class NoTextFileError(NotFoundError):
    """Like the files module: the file has no extracted text."""

    code = "files/no-text"


class FakeScanFilesApi(FakeFilesApi):
    """`FakeFilesApi` plus outlines and the failures the job must survive."""

    def __init__(self) -> None:
        """Start without outlines or failures."""
        super().__init__()
        self.outlines: dict[UUID, list[OutlineEntry]] = {}
        self.flat: set[UUID] = set()
        self.no_text: set[UUID] = set()
        self.broken: set[UUID] = set()

    async def read_outline(self, file_id: UUID) -> list[OutlineEntry]:
        """The configured table of contents."""
        return self.outlines.get(file_id, [])

    async def read_text_with_pages(self, file_id: UUID) -> FullText:
        """Text with offsets; `flat` files have none, `no_text` and `broken` raise."""
        if file_id in self.no_text:
            raise NoTextFileError()
        if file_id in self.broken:
            raise ValidationFailedError(support_details="extraction exploded")
        full = await super().read_text_with_pages(file_id)
        if file_id in self.flat:
            return FullText(file_id, full.text, ())
        return full

    async def page_count(self, file_id: UUID) -> int | None:
        """No count for `flat` files (Markdown and text have no pages)."""
        if file_id in self.flat:
            return None
        return await super().page_count(file_id)

    async def list_owned(self, owner_id: UUID, *, limit: int) -> list[FileRef]:
        """The owner's files, newest first."""
        owned = [f.ref for f in self.files.values() if f.ref.owner_id == owner_id]
        return list(reversed(owned))[:limit]
