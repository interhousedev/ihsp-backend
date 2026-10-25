"""SQL repository of text pages (`library.item_pages`)."""

from collections.abc import Sequence
from uuid import UUID

from app.modules.library.infrastructure.orm import ItemPage as PageRow
from app.modules.library.ports.page_repository import IndexedPage

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

INSERT_BATCH = 200


class SqlPageRepository:
    """Stores the extracted text of book and material files, page by page."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to the unit of work's session."""
        self.session = session

    async def replace(
        self, item_id: UUID, file_id: UUID, pages: Sequence[IndexedPage]
    ) -> None:
        """Replace all pages of the file (the scan job may run again)."""
        await self.delete(item_id, file_id)
        for start in range(0, len(pages), INSERT_BATCH):
            self.session.add_all(
                PageRow(
                    item_id=item_id,
                    file_id=file_id,
                    page=page.page,
                    text=page.text,
                    text_norm=page.text_norm,
                )
                for page in pages[start : start + INSERT_BATCH]
            )
            await self.session.flush()

    async def pages(
        self, item_id: UUID, file_id: UUID, page_from: int, page_to: int
    ) -> list[IndexedPage]:
        """Pages `page_from` to `page_to` inclusive, in order (missing ones skipped)."""
        rows = await self.session.execute(
            select(PageRow.page, PageRow.text, PageRow.text_norm)
            .where(
                PageRow.item_id == item_id,
                PageRow.file_id == file_id,
                PageRow.page.between(page_from, page_to),
            )
            .order_by(PageRow.page)
        )
        return [IndexedPage(page, text, norm) for page, text, norm in rows.all()]

    async def count(self, item_id: UUID, file_id: UUID) -> int:
        """How many pages of the file are indexed."""
        total = await self.session.scalar(
            select(func.count())
            .select_from(PageRow)
            .where(PageRow.item_id == item_id, PageRow.file_id == file_id)
        )
        return int(total or 0)

    async def delete(self, item_id: UUID, file_id: UUID) -> None:
        """Forget the pages of the file."""
        await self.session.execute(
            delete(PageRow).where(
                PageRow.item_id == item_id, PageRow.file_id == file_id
            )
        )
