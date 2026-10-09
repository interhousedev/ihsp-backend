"""SQL repository of reports, sanctions, suggestions, queues and upload counts."""

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from app.modules.library.domain.enums import (
    ItemStatus,
    ReportReason,
    ReportStatus,
    SanctionKind,
    SuggestionStatus,
    UploaderRole,
)
from app.modules.library.domain.moderation_entities import (
    BookSuggestion,
    QueueAgeStats,
    Report,
    ReportGroup,
    Sanction,
)
from app.modules.library.infrastructure.orm import BookDetails as BookRow
from app.modules.library.infrastructure.orm import BookSuggestion as SuggestionRow
from app.modules.library.infrastructure.orm import Item as ItemRow
from app.modules.library.infrastructure.orm import ItemFile as FileRow
from app.modules.library.infrastructure.orm import ItemReport as ReportRow
from app.modules.library.infrastructure.orm import MaterialDetails as MaterialRow
from app.modules.library.infrastructure.orm import Sanction as SanctionRow
from app.modules.library.ports.moderation_repository import QueueEntry

from sqlalchemy import (
    ColumnElement,
    and_,
    delete,
    exists,
    func,
    or_,
    select,
    update,
)
from sqlalchemy.ext.asyncio import AsyncSession

OPEN = ReportStatus.OPEN.value
LIVE_BOOK_STATUSES = (ItemStatus.PUBLISHED.value, ItemStatus.HELD.value)
UNFINISHED = (
    ItemStatus.DRAFT.value,
    ItemStatus.PENDING_REVIEW.value,
    ItemStatus.CHANGES_REQUESTED.value,
)
SECONDS_PER_HOUR = 3600.0

# - - - Row <-> entity - - -


def _report_from(row: ReportRow) -> Report:
    return Report(
        id=row.id,
        item_id=row.item_id,
        reporter_id=row.reporter_id,
        reporter_role=UploaderRole(row.reporter_role or UploaderRole.STUDENT.value),
        reason=ReportReason(row.reason),
        created_at=row.created_at,
        text=row.text,
        status=ReportStatus(row.status),
        handled_by=row.handled_by,
        handled_at=row.handled_at,
        action=row.action,
    )


def _sanction_from(row: SanctionRow) -> Sanction:
    return Sanction(
        id=row.id,
        user_id=row.user_id,
        kind=SanctionKind(row.kind),
        reason=row.reason,
        set_by=row.set_by,
        created_at=row.created_at,
        until=row.until,
        item_id=row.item_id,
    )


def _suggestion_from(row: SuggestionRow) -> BookSuggestion:
    return BookSuggestion(
        id=row.id,
        user_id=row.user_id,
        title=row.title,
        created_at=row.created_at,
        url=row.url,
        file_id=row.file_id,
        note=row.note,
        status=SuggestionStatus(row.status),
        handled_by=row.handled_by,
    )


def _waiting_since() -> ColumnElement[datetime]:
    """When an item entered the review queue: its submission, else its creation."""
    return func.coalesce(MaterialRow.submitted_at, ItemRow.created_at)


def _is_pending() -> ColumnElement[bool]:
    return and_(
        ItemRow.kind == "material", ItemRow.status == ItemStatus.PENDING_REVIEW.value
    )


class SqlModerationRepository:
    """Stores the data of the materials area in schema `library`."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to the unit of work's session."""
        self.session = session

    # - - - Reports - - -

    async def add_report(self, report: Report) -> None:
        """Insert a report (one open report per item, reporter and reason)."""
        self.session.add(
            ReportRow(
                id=report.id,
                item_id=report.item_id,
                reporter_id=report.reporter_id,
                reporter_role=report.reporter_role.value,
                reason=report.reason.value,
                text=report.text,
                status=report.status.value,
                handled_by=report.handled_by,
                handled_at=report.handled_at,
                action=report.action,
                created_at=report.created_at,
            )
        )
        await self.session.flush()

    async def has_open_report(
        self, item_id: UUID, reporter_id: UUID, reason: str
    ) -> bool:
        """True when this person already has an open report with this reason."""
        query = select(
            exists().where(
                ReportRow.item_id == item_id,
                ReportRow.reporter_id == reporter_id,
                ReportRow.reason == reason,
                ReportRow.status == OPEN,
            )
        )
        return bool(await self.session.scalar(query))

    async def open_reports(self, item_id: UUID) -> list[Report]:
        """Open reports of the item, oldest first."""
        rows = await self.session.execute(
            select(ReportRow)
            .where(ReportRow.item_id == item_id, ReportRow.status == OPEN)
            .order_by(ReportRow.created_at, ReportRow.id)
        )
        return [_report_from(row) for row in rows.scalars()]

    async def get_report(self, report_id: UUID) -> Report | None:
        """The report or None."""
        row = await self.session.get(ReportRow, report_id)
        return _report_from(row) if row else None

    async def close_reports(
        self,
        item_id: UUID,
        status: ReportStatus,
        *,
        handled_by: UUID | None,
        at: datetime,
        action: str,
    ) -> int:
        """Mark every open report of the item `upheld` or `dismissed`; the count."""
        result = await self.session.execute(
            update(ReportRow)
            .where(ReportRow.item_id == item_id, ReportRow.status == OPEN)
            .values(
                status=status.value, handled_by=handled_by, handled_at=at, action=action
            )
            .returning(ReportRow.id)
        )
        return len(result.all())

    async def report_times(self, reporter_id: UUID, since: datetime) -> list[datetime]:
        """When the person filed reports since the moment (for the daily limit)."""
        rows = await self.session.execute(
            select(ReportRow.created_at)
            .where(ReportRow.reporter_id == reporter_id, ReportRow.created_at >= since)
            .order_by(ReportRow.created_at)
        )
        return list(rows.scalars())

    async def report_groups(self, item_ids: Sequence[UUID]) -> list[ReportGroup]:
        """Open reports of the items grouped by item and reason."""
        if not item_ids:
            return []
        rows = await self.session.execute(
            select(ReportRow)
            .where(ReportRow.item_id.in_(set(item_ids)), ReportRow.status == OPEN)
            .order_by(ReportRow.created_at, ReportRow.id)
        )
        grouped: dict[tuple[UUID, str], list[ReportRow]] = {}
        for row in rows.scalars():
            grouped.setdefault((row.item_id, row.reason), []).append(row)
        return [
            ReportGroup(
                item_id=item_id,
                reason=ReportReason(reason),
                count=len(group),
                report_ids=tuple(row.id for row in group),
                first_at=group[0].created_at,
            )
            for (item_id, reason), group in grouped.items()
        ]

    # - - - Sanctions - - -

    async def add_sanction(self, sanction: Sanction) -> None:
        """Insert a warning or an upload ban."""
        self.session.add(
            SanctionRow(
                id=sanction.id,
                user_id=sanction.user_id,
                kind=sanction.kind.value,
                until=sanction.until,
                reason=sanction.reason,
                item_id=sanction.item_id,
                set_by=sanction.set_by,
                created_at=sanction.created_at,
            )
        )
        await self.session.flush()

    async def list_sanctions(self, user_id: UUID | None = None) -> list[Sanction]:
        """Sanctions, newest first; of one user when given."""
        query = select(SanctionRow).order_by(
            SanctionRow.created_at.desc(), SanctionRow.id.desc()
        )
        if user_id is not None:
            query = query.where(SanctionRow.user_id == user_id)
        return [_sanction_from(row) for row in await self.session.scalars(query)]

    async def active_ban(self, user_id: UUID, now: datetime) -> Sanction | None:
        """The upload ban in force at `now`, or None."""
        row = await self.session.scalar(
            select(SanctionRow)
            .where(
                SanctionRow.user_id == user_id,
                SanctionRow.kind == SanctionKind.UPLOAD_BAN.value,
                or_(SanctionRow.until.is_(None), SanctionRow.until > now),
            )
            .order_by(SanctionRow.created_at.desc())
            .limit(1)
        )
        return _sanction_from(row) if row else None

    # - - - Suggestions - - -

    async def add_suggestion(self, suggestion: BookSuggestion) -> None:
        """Insert a book suggestion."""
        self.session.add(
            SuggestionRow(
                id=suggestion.id,
                user_id=suggestion.user_id,
                title=suggestion.title,
                url=suggestion.url,
                file_id=suggestion.file_id,
                note=suggestion.note,
                status=suggestion.status.value,
                handled_by=suggestion.handled_by,
                created_at=suggestion.created_at,
            )
        )
        await self.session.flush()

    async def get_suggestion(self, suggestion_id: UUID) -> BookSuggestion | None:
        """The suggestion or None."""
        row = await self.session.get(SuggestionRow, suggestion_id)
        return _suggestion_from(row) if row else None

    async def save_suggestion(self, suggestion: BookSuggestion) -> None:
        """Update status and handler of a suggestion."""
        row = await self.session.get(SuggestionRow, suggestion.id)
        if row is None:
            raise LookupError(f"suggestion {suggestion.id} is not stored")
        row.status = suggestion.status.value
        row.handled_by = suggestion.handled_by
        await self.session.flush()

    async def new_suggestions(self, *, limit: int, offset: int) -> list[BookSuggestion]:
        """Suggestions nobody decided yet, oldest first."""
        rows = await self.session.scalars(
            select(SuggestionRow)
            .where(SuggestionRow.status == SuggestionStatus.NEW.value)
            .order_by(SuggestionRow.created_at, SuggestionRow.id)
            .limit(limit)
            .offset(offset)
        )
        return [_suggestion_from(row) for row in rows]

    # - - - Queue - - -

    async def review_queue(self, *, limit: int, offset: int) -> list[QueueEntry]:
        """Materials in `pending_review`, oldest submission first."""
        waiting = _waiting_since()
        rows = await self.session.execute(
            select(ItemRow.id, waiting)
            .join(MaterialRow, MaterialRow.item_id == ItemRow.id)
            .where(_is_pending())
            .order_by(waiting, ItemRow.id)
            .limit(limit)
            .offset(offset)
        )
        return [QueueEntry(item_id, at) for item_id, at in rows.all()]

    async def report_queue(
        self, *, held: bool, limit: int, offset: int
    ) -> list[QueueEntry]:
        """Items with open reports (`held` items, or published ones), oldest first."""
        first = (
            select(
                ReportRow.item_id.label("item_id"),
                func.min(ReportRow.created_at).label("first_at"),
            )
            .where(ReportRow.status == OPEN)
            .group_by(ReportRow.item_id)
            .subquery()
        )
        at = func.coalesce(first.c.first_at, ItemRow.updated_at)
        query = select(ItemRow.id, at.label("at"))
        if held:
            query = query.outerjoin(first, first.c.item_id == ItemRow.id).where(
                ItemRow.status == ItemStatus.HELD.value
            )
        else:
            query = query.join(first, first.c.item_id == ItemRow.id).where(
                ItemRow.status == ItemStatus.PUBLISHED.value
            )
        rows = await self.session.execute(
            query.order_by(at, ItemRow.id).limit(limit).offset(offset)
        )
        return [QueueEntry(item_id, when) for item_id, when in rows.all()]

    async def rights_candidates(self) -> list[UUID]:
        """Ids of live books whose rights may need a look (checked in Python)."""
        rows = await self.session.scalars(
            select(ItemRow.id)
            .join(BookRow, BookRow.item_id == ItemRow.id)
            .where(
                ItemRow.status.in_(LIVE_BOOK_STATUSES),
                or_(
                    BookRow.rights_checked_at.is_(None), BookRow.rights == "permission"
                ),
            )
            .order_by(ItemRow.created_at, ItemRow.id)
        )
        return list(rows)

    async def pending_times(self) -> list[QueueEntry]:
        """Every material in `pending_review` with its submission time."""
        waiting = _waiting_since()
        rows = await self.session.execute(
            select(ItemRow.id, waiting)
            .join(MaterialRow, MaterialRow.item_id == ItemRow.id)
            .where(_is_pending())
            .order_by(waiting, ItemRow.id)
        )
        return [QueueEntry(item_id, at) for item_id, at in rows.all()]

    async def pending_positions(self, item_ids: Sequence[UUID]) -> dict[UUID, int]:
        """1-based place in the review queue of those items that are waiting."""
        if not item_ids:
            return {}
        waiting = _waiting_since()
        place = func.row_number().over(order_by=(waiting, ItemRow.id))
        ranked = (
            select(ItemRow.id, place.label("place"))
            .join(MaterialRow, MaterialRow.item_id == ItemRow.id)
            .where(_is_pending())
            .subquery()
        )
        rows = await self.session.execute(
            select(ranked.c.id, ranked.c.place).where(ranked.c.id.in_(set(item_ids)))
        )
        return {item_id: int(place) for item_id, place in rows.all()}

    async def queue_age_stats(self, now: datetime) -> QueueAgeStats:
        """Length, oldest and average wait of the review queue."""
        waits = [
            max((now - entry.at).total_seconds(), 0.0) / SECONDS_PER_HOUR
            for entry in await self.pending_times()
        ]
        if not waits:
            return QueueAgeStats(0, None, None)
        return QueueAgeStats(len(waits), max(waits), sum(waits) / len(waits))

    # - - - Uploads of one person - - -

    async def uploads_page(
        self,
        owner_id: UUID,
        *,
        status: ItemStatus | None,
        limit: int,
        after: tuple[datetime, UUID] | None,
    ) -> list[UUID]:
        """Ids of the person's materials, newest first, after a keyset position."""
        query = select(ItemRow.id).where(
            ItemRow.owner_id == owner_id, ItemRow.kind == "material"
        )
        if status is not None:
            query = query.where(ItemRow.status == status.value)
        if after is not None:
            created_at, last_id = after
            query = query.where(
                or_(
                    ItemRow.created_at < created_at,
                    and_(ItemRow.created_at == created_at, ItemRow.id < last_id),
                )
            )
        rows = await self.session.scalars(
            query.order_by(ItemRow.created_at.desc(), ItemRow.id.desc()).limit(limit)
        )
        return list(rows)

    async def upload_times(
        self, user_id: UUID, since: datetime, *, exclude: UUID | None = None
    ) -> list[datetime]:
        """Submission times of the person's materials since the moment."""
        query = select(MaterialRow.submitted_at).where(
            MaterialRow.uploader_id == user_id, MaterialRow.submitted_at >= since
        )
        if exclude is not None:
            query = query.where(MaterialRow.item_id != exclude)
        rows = await self.session.scalars(query.order_by(MaterialRow.submitted_at))
        return [when for when in rows if when is not None]

    async def count_uploads(self, user_id: UUID, since: datetime) -> int:
        """How many materials the person submitted since the moment."""
        return len(await self.upload_times(user_id, since))

    async def open_versions(self, item_id: UUID) -> list[UUID]:
        """Unfinished new versions (draft, queued or sent back) of the item."""
        rows = await self.session.scalars(
            select(ItemRow.id)
            .where(ItemRow.supersedes_id == item_id, ItemRow.status.in_(UNFINISHED))
            .order_by(ItemRow.created_at, ItemRow.id)
        )
        return list(rows)

    async def owner_item_ids(
        self, owner_id: UUID, statuses: Sequence[ItemStatus]
    ) -> list[UUID]:
        """Ids of the person's materials in those statuses."""
        rows = await self.session.scalars(
            select(ItemRow.id)
            .where(
                ItemRow.owner_id == owner_id,
                ItemRow.kind == "material",
                ItemRow.status.in_([status.value for status in statuses]),
            )
            .order_by(ItemRow.created_at, ItemRow.id)
        )
        return list(rows)

    async def delete_draft(self, item_id: UUID) -> None:
        """Remove a never-submitted draft with its details and file rows."""
        await self.session.execute(
            delete(ItemRow).where(
                ItemRow.id == item_id, ItemRow.status == ItemStatus.DRAFT.value
            )
        )

    async def purgeable_items(
        self, *, rejected_before: datetime, unpublished_before: datetime, limit: int
    ) -> list[UUID]:
        """Materials that were rejected or unpublished long ago and still hold files."""
        rows = await self.session.scalars(
            select(ItemRow.id)
            .where(
                ItemRow.kind == "material",
                or_(
                    and_(
                        ItemRow.status == ItemStatus.REJECTED.value,
                        ItemRow.updated_at < rejected_before,
                    ),
                    and_(
                        ItemRow.status == ItemStatus.UNPUBLISHED.value,
                        ItemRow.updated_at < unpublished_before,
                    ),
                ),
                exists().where(FileRow.item_id == ItemRow.id),
            )
            .order_by(ItemRow.updated_at, ItemRow.id)
            .limit(limit)
        )
        return list(rows)
