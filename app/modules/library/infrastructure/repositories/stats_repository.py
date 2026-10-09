"""SQL repository of item statistics (taxonomy area)."""

from datetime import date, datetime
from uuid import UUID

from app.modules.library.domain.enums import (
    ItemKind,
    ItemStatus,
    ReportReason,
)
from app.modules.library.infrastructure.orm import Item as ItemRow
from app.modules.library.infrastructure.orm import ItemReport as ReportRow
from app.modules.library.infrastructure.orm import ItemStat as StatRow
from app.modules.library.infrastructure.orm import ItemSubject as ItemSubjectRow

from sqlalchemy import Date, cast, desc, func, literal_column, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession


class SqlStatsRepository:
    """Stores daily item counters in schema `library` and sums them up."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to the unit of work's session."""
        self.session = session

    async def upsert_day(
        self, item_id: UUID, day: date, opens: int, readers: int, offline_saves: int
    ) -> None:
        """Set the counters of the item on the day (repeating the call changes nothing)."""
        values = {"opens": opens, "readers": readers, "offline_saves": offline_saves}
        statement = insert(StatRow).values(item_id=item_id, day=day, **values)
        await self.session.execute(
            statement.on_conflict_do_update(
                index_elements=[StatRow.item_id, StatRow.day],
                set_={**values, "updated_at": func.now()},
            )
        )

    async def totals(self, start: date, end: date) -> tuple[int, int]:
        """`(opens, readers)` over the days; readers add up each item's daily readers."""
        row = (
            await self.session.execute(
                select(
                    func.coalesce(func.sum(StatRow.opens), 0),
                    func.coalesce(func.sum(StatRow.readers), 0),
                ).where(StatRow.day.between(start, end))
            )
        ).one()
        return int(row[0]), int(row[1])

    async def top_items(
        self, start: date, end: date, limit: int
    ) -> list[tuple[UUID, int]]:
        """`(item id, opens)` of the most opened items in the window."""
        opens = func.sum(StatRow.opens).label("opens")
        rows = await self.session.execute(
            select(StatRow.item_id, opens)
            .where(StatRow.day.between(start, end))
            .group_by(StatRow.item_id)
            .having(opens > 0)
            .order_by(desc(opens), StatRow.item_id)
            .limit(limit)
        )
        return [(item_id, int(total)) for item_id, total in rows.all()]

    async def item_status_counts(self) -> dict[ItemStatus, int]:
        """How many items are in each status (statuses without items are absent)."""
        rows = await self.session.execute(
            select(ItemRow.status, func.count()).group_by(ItemRow.status)
        )
        return {ItemStatus(status): int(count) for status, count in rows.all()}

    async def report_counts(
        self, since: datetime, until: datetime
    ) -> dict[ReportReason, int]:
        """Reports filed in `[since, until)` by reason (any status)."""
        rows = await self.session.execute(
            select(ReportRow.reason, func.count())
            .where(ReportRow.created_at >= since, ReportRow.created_at < until)
            .group_by(ReportRow.reason)
        )
        return {ReportReason(reason): int(count) for reason, count in rows.all()}

    async def uploads_by_day(self, since: datetime, until: datetime) -> dict[date, int]:
        """Materials created in `[since, until)` per UTC day (days without are absent)."""
        # A literal zone keeps the SELECT and GROUP BY expressions identical.
        day = cast(func.timezone(literal_column("'UTC'"), ItemRow.created_at), Date)
        rows = await self.session.execute(
            select(day, func.count())
            .where(
                ItemRow.kind == ItemKind.MATERIAL.value,
                ItemRow.created_at >= since,
                ItemRow.created_at < until,
            )
            .group_by(day)
        )
        return {uploaded: int(count) for uploaded, count in rows.all()}

    async def subject_ids_with_materials(self) -> set[UUID]:
        """Subjects that have a published book or material."""
        rows = await self.session.execute(
            select(ItemSubjectRow.subject_id)
            .join(ItemRow, ItemRow.id == ItemSubjectRow.item_id)
            .where(
                ItemRow.status == ItemStatus.PUBLISHED.value,
                ItemRow.kind.in_([ItemKind.BOOK.value, ItemKind.MATERIAL.value]),
            )
            .distinct()
        )
        return set(rows.scalars())
