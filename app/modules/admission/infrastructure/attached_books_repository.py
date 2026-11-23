"""Books staff attached to students."""

from uuid import UUID

from app.modules.admission.domain.courses import AttachedBook
from app.modules.admission.infrastructure.orm.attached_books import AttachedBookRow
from app.shared.ids import new_id

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession


def _book(row: AttachedBookRow) -> AttachedBook:
    return AttachedBook(
        student_id=row.student_id,
        item_id=row.item_id,
        attached_by=row.attached_by,
        note=row.note,
        id=row.id,
        created_at=row.created_at,
    )


class SqlAttachedBookRepository:
    """Attachment rows."""

    def __init__(self, session: AsyncSession) -> None:
        """Keep the open session."""
        self._s = session

    async def list_for(self, student_id: UUID) -> list[AttachedBook]:
        """Return the student's attachments, newest first."""
        rows = await self._s.scalars(
            select(AttachedBookRow)
            .where(AttachedBookRow.student_id == student_id)
            .order_by(AttachedBookRow.created_at.desc(), AttachedBookRow.id)
        )
        return [_book(r) for r in rows]

    async def add(self, book: AttachedBook) -> AttachedBook:
        """Insert the attachment; an existing one is returned unchanged."""
        await self._s.execute(
            pg_insert(AttachedBookRow)
            .values(
                id=new_id(),
                student_id=book.student_id,
                item_id=book.item_id,
                attached_by=book.attached_by,
                note=book.note,
            )
            .on_conflict_do_nothing(index_elements=["student_id", "item_id"])
        )
        row = await self._s.scalar(
            select(AttachedBookRow)
            .where(
                AttachedBookRow.student_id == book.student_id,
                AttachedBookRow.item_id == book.item_id,
            )
            .execution_options(populate_existing=True)
        )
        assert row is not None
        return _book(row)

    async def remove(self, student_id: UUID, item_id: UUID) -> bool:
        """Delete the attachment; False when there was none."""
        result = await self._s.execute(
            delete(AttachedBookRow)
            .where(
                AttachedBookRow.student_id == student_id,
                AttachedBookRow.item_id == item_id,
            )
            .returning(AttachedBookRow.id)
        )
        return result.first() is not None
