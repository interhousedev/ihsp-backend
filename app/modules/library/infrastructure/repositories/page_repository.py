"""SQL repository of text pages (`library.item_pages`)."""

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from app.modules.library.domain.page_search import fold_text
from app.modules.library.infrastructure.orm import ItemPage as PageRow
from app.modules.library.ports.page_repository import IndexedPage
from app.shared.contracts.files import TextBox

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

INSERT_BATCH = 200
_COLUMNS = (
    PageRow.page,
    PageRow.text,
    PageRow.text_norm,
    PageRow.source,
    PageRow.boxes,
)


def _row(box: TextBox) -> tuple[int, int, float, float, float, float]:
    return (box.start, box.end, box.x, box.y, box.w, box.h)


def _page(row: Any) -> IndexedPage:
    page, text, norm, source, boxes = row
    return IndexedPage(
        page,
        text,
        norm,
        source,
        tuple(
            TextBox(int(b[0]), int(b[1]), b[2], b[3], b[4], b[5]) for b in boxes or ()
        ),
    )


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
                    text_fold=fold_text(page.text_norm),
                    source=page.source,
                    boxes=[list(_row(box)) for box in page.boxes] or None,
                )
                for page in pages[start : start + INSERT_BATCH]
            )
            await self.session.flush()

    async def pages(
        self, item_id: UUID, file_id: UUID, page_from: int, page_to: int
    ) -> list[IndexedPage]:
        """Pages `page_from` to `page_to` inclusive, in order (missing ones skipped)."""
        rows = await self.session.execute(
            select(*_COLUMNS)
            .where(
                PageRow.item_id == item_id,
                PageRow.file_id == file_id,
                PageRow.page.between(page_from, page_to),
            )
            .order_by(PageRow.page)
        )
        return [_page(row) for row in rows.all()]

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

    async def search(
        self, item_id: UUID, file_id: UUID, needle: str, limit: int
    ) -> list[IndexedPage]:
        """Pages whose folded text contains `needle`, in order, at most `limit`."""
        rows = await self.session.execute(
            select(*_COLUMNS)
            .where(
                PageRow.item_id == item_id,
                PageRow.file_id == file_id,
                func.coalesce(PageRow.text_fold, PageRow.text_norm).contains(
                    needle, autoescape=True
                ),
            )
            .order_by(PageRow.page)
            .limit(limit)
        )
        return [_page(row) for row in rows.all()]

    async def stale_files(
        self, after: UUID | None, limit: int
    ) -> list[tuple[UUID, UUID]]:
        """`(item_id, file_id)` of files with pages not yet folded, by file id."""
        query = (
            select(PageRow.item_id, PageRow.file_id)
            .where(PageRow.text_fold.is_(None))
            .group_by(PageRow.item_id, PageRow.file_id)
            .order_by(PageRow.file_id)
            .limit(limit)
        )
        if after is not None:
            query = query.where(PageRow.file_id > after)
        rows = await self.session.execute(query)
        return [(item_id, file_id) for item_id, file_id in rows.all()]
