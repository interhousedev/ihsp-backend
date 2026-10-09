"""SQL repository of the external area: feeds, the field map, stored-record lookups."""

from collections.abc import Sequence
from uuid import UUID

from app.modules.library.domain.entities import Item
from app.modules.library.domain.enums import (
    ExternalSource,
    ItemKind,
    ItemStatus,
    Visibility,
)
from app.modules.library.domain.errors import DuplicateItemError
from app.modules.library.domain.external_feed import (
    Feed,
    FeedParams,
    FeedRunStatus,
    FieldMapEntry,
)
from app.modules.library.infrastructure.orm import ExternalDetails as DetailsRow
from app.modules.library.infrastructure.orm import ExternalFeed as FeedRow
from app.modules.library.infrastructure.orm import ExternalFieldMap as FieldMapRow
from app.modules.library.infrastructure.orm import Item as ItemRow
from app.modules.library.infrastructure.repositories.item_repository import (
    SqlItemRepository,
)

from sqlalchemy import delete, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

SOURCE = ExternalSource.UNILIBRARY


def _feed_from(row: FeedRow) -> Feed:
    status: FeedRunStatus | None = None
    if row.last_status == "ok":
        status = "ok"
    elif row.last_status == "error":
        status = "error"
    return Feed(
        id=row.id,
        name=row.name,
        source=ExternalSource(row.source),
        params=FeedParams.model_validate(row.params),
        enabled=row.enabled,
        max_items=row.max_items,
        estimate=row.estimate,
        last_run_at=row.last_run_at,
        last_status=status,
        last_count=row.last_count,
        last_error=row.last_error,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _apply_feed(row: FeedRow, feed: Feed) -> None:
    row.name = feed.name
    row.source = feed.source.value
    row.params = feed.params.model_dump(mode="json")
    row.enabled = feed.enabled
    row.max_items = feed.max_items
    row.estimate = feed.estimate
    row.last_run_at = feed.last_run_at
    row.last_status = feed.last_status
    row.last_count = feed.last_count
    row.last_error = feed.last_error
    row.updated_at = feed.updated_at


class SqlExternalRepository:
    """Stores feeds and the field map in schema `library`."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to the unit of work's session."""
        self.session = session

    # - - - Stored records - - -

    async def item_ids_by_external(
        self, source: ExternalSource, external_ids: Sequence[str]
    ) -> dict[str, UUID]:
        """Item ids of the records already stored (others are absent)."""
        if not external_ids:
            return {}
        rows = await self.session.execute(
            select(DetailsRow.external_id, DetailsRow.item_id).where(
                DetailsRow.source == source.value,
                DetailsRow.external_id.in_(set(external_ids)),
            )
        )
        return dict(rows.tuples().all())

    async def add_pinned(self, item: Item) -> None:
        """Store a new external item (a pin); the session stays usable after a clash.

        The insert runs in a savepoint, so a unique-key clash with a record pinned a
        moment earlier rolls back only the insert and becomes `DuplicateItemError`.
        """
        try:
            async with self.session.begin_nested():
                await SqlItemRepository(self.session).add(item)
        except IntegrityError as error:
            external_id = item.external.external_id if item.external else "?"
            raise DuplicateItemError(
                support_details=f"external record {external_id} is already stored"
            ) from error

    async def hidden_item_ids(self, *, limit: int) -> list[UUID]:
        """Stored external items a librarian hid: unpublished or `hidden`."""
        query = (
            select(ItemRow.id)
            .where(
                ItemRow.kind == ItemKind.EXTERNAL.value,
                or_(
                    ItemRow.status == ItemStatus.UNPUBLISHED.value,
                    ItemRow.visibility == Visibility.HIDDEN.value,
                ),
            )
            .order_by(ItemRow.updated_at.desc(), ItemRow.id)
            .limit(limit)
        )
        return list((await self.session.execute(query)).scalars())

    # - - - Feeds - - -

    async def list_feeds(self) -> list[Feed]:
        """All feeds, oldest first."""
        rows = await self.session.execute(
            select(FeedRow).order_by(FeedRow.created_at, FeedRow.id)
        )
        return [_feed_from(row) for row in rows.scalars()]

    async def get_feed(self, feed_id: UUID) -> Feed | None:
        """The feed or None."""
        row = await self.session.get(FeedRow, feed_id)
        return _feed_from(row) if row else None

    async def add_feed(self, feed: Feed) -> None:
        """Insert a feed."""
        row = FeedRow(id=feed.id, created_at=feed.created_at)
        _apply_feed(row, feed)
        self.session.add(row)
        await self.session.flush()

    async def save_feed(self, feed: Feed) -> None:
        """Update a feed."""
        row = await self.session.get(FeedRow, feed.id)
        if row is None:
            raise LookupError(f"feed {feed.id} is not stored")
        _apply_feed(row, feed)
        await self.session.flush()

    async def delete_feed(self, feed_id: UUID) -> bool:
        """Remove a feed; False when there was none."""
        row = await self.session.get(FeedRow, feed_id)
        if row is None:
            return False
        await self.session.delete(row)
        await self.session.flush()
        return True

    # - - - Field map - - -

    async def field_map(self) -> list[FieldMapEntry]:
        """The whole map, ordered by field then subject."""
        rows = await self.session.execute(
            select(FieldMapRow)
            .where(FieldMapRow.source == SOURCE.value)
            .order_by(FieldMapRow.external_field_id, FieldMapRow.subject_id)
        )
        return [
            FieldMapEntry(row.subject_id, row.external_field_id)
            for row in rows.scalars()
        ]

    async def replace_field_map(self, entries: Sequence[FieldMapEntry]) -> None:
        """Replace the whole map."""
        await self.session.execute(
            delete(FieldMapRow).where(FieldMapRow.source == SOURCE.value)
        )
        for entry in dict.fromkeys(entries):
            self.session.add(
                FieldMapRow(
                    subject_id=entry.subject_id,
                    source=SOURCE.value,
                    external_field_id=entry.external_field_id,
                )
            )
        await self.session.flush()
