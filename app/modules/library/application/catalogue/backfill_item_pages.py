"""Backfill of stored page text: folded text, source and word boxes for old items."""

from uuid import UUID

from app.modules.library.application.catalogue.common import require_librarian
from app.modules.library.application.catalogue.process_item_file import (
    Extracted,
    index_pages,
)
from app.modules.library.domain.catalogue_text import split_pages
from app.modules.library.domain.enums import TextStatus
from app.modules.library.domain.search_query import item_search_language
from app.modules.library.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from app.shared.base_error import BaseError
from app.shared.contracts.files import FilesApi
from app.shared.tasks import TaskKicker

BATCH = 100
BACKFILL_TASK = "library.backfill_item_pages"
REINDEX_TASK = "library.reindex_item_pages"


class ReindexItemPages:
    """Re-read one file's text and boxes and replace its pages; nothing else changes."""

    def __init__(self, *, uow_factory: UowFactory, files: FilesApi) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
        self.files = files

    async def execute(self, item_id: UUID, file_id: UUID) -> bool:
        """True when the pages were replaced; a missing or textless file is skipped."""
        extracted = Extracted()
        try:
            full = await self.files.read_text_with_pages(file_id)
            extracted.pages = split_pages(full.text, full.page_starts)
            extracted.layouts = await self.files.read_page_layouts(file_id)
        except BaseError:
            return False
        async with self.uow_factory() as uow:
            item = await uow.items.get(item_id, lock=True)
            stored = item.file(file_id) if item else None
            if (
                item is None
                or stored is None
                or stored.text_status is not (TextStatus.READY)
            ):
                return False
            language = item_search_language(item.language)
            pages = index_pages(extracted.pages, extracted.layouts, language)
            await uow.pages.replace(item_id, file_id, pages)
            await uow.commit()
        return True


class BackfillItemPages:
    """Starts a reindex task for every file whose pages are not yet folded."""

    def __init__(self, *, uow_factory: UowFactory, kicker: TaskKicker) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
        self.kicker = kicker

    async def request(self, actor: Actor) -> None:
        """A librarian starts the job in the background."""
        require_librarian(actor)
        await self.kicker.kick(BACKFILL_TASK)

    async def execute(self, *, limit: int = 1000) -> int:
        """Kick a reindex for at most `limit` stale files; how many were kicked."""
        kicked = 0
        after: UUID | None = None
        while kicked < limit:
            async with self.uow_factory() as uow:
                files = await uow.pages.stale_files(after, min(BATCH, limit - kicked))
            if not files:
                break
            for item_id, file_id in files:
                await self.kicker.kick(
                    REINDEX_TASK, item_id=str(item_id), file_id=str(file_id)
                )
            kicked += len(files)
            after = files[-1][1]
        return kicked
