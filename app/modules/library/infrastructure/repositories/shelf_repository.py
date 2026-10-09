"""SQL repository of shelves."""

from collections.abc import Sequence
from uuid import UUID

from app.modules.library.domain.enums import ItemStatus, ShelfState, Visibility
from app.modules.library.domain.reader_shelf import ShelfEntry
from app.modules.library.infrastructure.orm import Item as ItemRow
from app.modules.library.infrastructure.orm import ShelfEntry as ShelfRow
from app.modules.library.infrastructure.repositories.rowcount import rows_affected
from app.modules.library.ports.shelf_repository import ShelfCursor
from app.shared.ids import new_id

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession


def _entry_from(row: ShelfRow) -> ShelfEntry:
    return ShelfEntry(
        user_id=row.user_id,
        item_id=row.item_id,
        state=ShelfState(row.state),
        finished_at=row.finished_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class SqlShelfRepository:
    """Stores shelf entries in `library.shelf_entries`."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to the unit of work's session."""
        self.session = session

    async def states(
        self, user_id: UUID, item_ids: Sequence[UUID]
    ) -> dict[UUID, ShelfState]:
        """Shelf state of the items on the user's shelf (others are absent)."""
        if not item_ids:
            return {}
        rows = await self.session.execute(
            select(ShelfRow.item_id, ShelfRow.state).where(
                ShelfRow.user_id == user_id, ShelfRow.item_id.in_(set(item_ids))
            )
        )
        return {item_id: ShelfState(state) for item_id, state in rows.all()}

    # - - - Added by the reader area - - -

    async def get(self, user_id: UUID, item_id: UUID) -> ShelfEntry | None:
        """The entry or None."""
        row = (
            await self.session.execute(
                select(ShelfRow).where(
                    ShelfRow.user_id == user_id, ShelfRow.item_id == item_id
                )
            )
        ).scalar_one_or_none()
        return _entry_from(row) if row else None

    async def save(self, entry: ShelfEntry) -> None:
        """Insert the entry or replace the state of the existing one."""
        values = {
            "state": entry.state.value,
            "finished_at": entry.finished_at,
            "updated_at": entry.updated_at,
        }
        statement = insert(ShelfRow).values(
            id=new_id(),
            user_id=entry.user_id,
            item_id=entry.item_id,
            created_at=entry.created_at,
            **values,
        )
        await self.session.execute(
            statement.on_conflict_do_update(
                index_elements=[ShelfRow.user_id, ShelfRow.item_id], set_=values
            )
        )

    async def remove(self, user_id: UUID, item_id: UUID) -> bool:
        """Delete the entry; True when there was one."""
        result = await self.session.execute(
            delete(ShelfRow).where(
                ShelfRow.user_id == user_id, ShelfRow.item_id == item_id
            )
        )
        return bool(rows_affected(result))

    async def list_page(
        self,
        user_id: UUID,
        *,
        state: ShelfState | None,
        after: ShelfCursor | None,
        limit: int,
    ) -> list[ShelfEntry]:
        """Entries, most recently changed first, continuing after the cursor."""
        query = select(ShelfRow).where(ShelfRow.user_id == user_id)
        if state is not None:
            query = query.where(ShelfRow.state == state.value)
        if after is not None:
            query = query.where(
                or_(
                    ShelfRow.updated_at < after.updated_at,
                    and_(
                        ShelfRow.updated_at == after.updated_at,
                        ShelfRow.item_id < after.item_id,
                    ),
                )
            )
        query = query.order_by(ShelfRow.updated_at.desc(), ShelfRow.item_id.desc())
        rows = await self.session.execute(query.limit(limit))
        return [_entry_from(row) for row in rows.scalars()]

    async def counts(
        self, user_id: UUID, *, listed_only: bool = False
    ) -> dict[ShelfState, int]:
        """How many entries are in each state (states without entries are absent).

        `listed_only` keeps entries of published, non-hidden items: the same rule as
        `domain.access.is_listed`, written as SQL so counting needs no item loading.
        """
        query = (
            select(ShelfRow.state, func.count())
            .where(ShelfRow.user_id == user_id)
            .group_by(ShelfRow.state)
        )
        if listed_only:
            query = query.join(ItemRow, ItemRow.id == ShelfRow.item_id).where(
                ItemRow.status == ItemStatus.PUBLISHED.value,
                ItemRow.visibility != Visibility.HIDDEN.value,
            )
        rows = await self.session.execute(query)
        return {ShelfState(state): count for state, count in rows.all()}

    async def delete_all(self, user_id: UUID) -> int:
        """Delete the whole shelf of the user (account closure)."""
        result = await self.session.execute(
            delete(ShelfRow).where(ShelfRow.user_id == user_id)
        )
        return rows_affected(result)
