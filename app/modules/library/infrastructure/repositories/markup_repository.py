"""SQL repository of page markup."""

from uuid import UUID

from app.modules.library.domain.reader_markup import Markup, pages_to_dict, parse_pages
from app.modules.library.infrastructure.orm import ReaderMarkup as MarkupRow
from app.modules.library.infrastructure.repositories.rowcount import rows_affected

from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession


class SqlMarkupRepository:
    """Stores one document per user and item in `library.reader_markup`."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to the unit of work's session."""
        self.session = session

    async def get(self, user_id: UUID, item_id: UUID) -> Markup | None:
        """The user's markup of the item, or None."""
        row = await self.session.get(MarkupRow, (user_id, item_id))
        if row is None:
            return None
        return Markup(
            user_id=row.user_id,
            item_id=row.item_id,
            file_id=row.file_id,
            pages=parse_pages(row.pages),
            updated_at=row.updated_at,
        )

    async def save(self, markup: Markup) -> None:
        """Insert the document or replace the user's document of the item."""
        values = {
            "file_id": markup.file_id,
            "pages": pages_to_dict(markup.pages),
            "updated_at": markup.updated_at,
        }
        statement = insert(MarkupRow).values(
            user_id=markup.user_id,
            item_id=markup.item_id,
            created_at=markup.updated_at,
            **values,
        )
        await self.session.execute(
            statement.on_conflict_do_update(
                index_elements=[MarkupRow.user_id, MarkupRow.item_id], set_=values
            )
        )

    async def delete(self, user_id: UUID, item_id: UUID) -> None:
        """Remove the user's markup of the item."""
        await self.session.execute(
            delete(MarkupRow).where(
                MarkupRow.user_id == user_id, MarkupRow.item_id == item_id
            )
        )

    async def delete_all(self, user_id: UUID) -> int:
        """Delete all markup of the user (account closure)."""
        result = await self.session.execute(
            delete(MarkupRow).where(MarkupRow.user_id == user_id)
        )
        return rows_affected(result)
