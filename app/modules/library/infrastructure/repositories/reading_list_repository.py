"""SQL repository of reading lists (taxonomy area)."""

from collections.abc import Collection, Sequence
from uuid import UUID

from app.modules.library.domain.enums import (
    Importance,
    ItemStatus,
    ListScope,
    ListStatus,
    Visibility,
)
from app.modules.library.domain.reading_list import ReadingList, ReadingListEntry
from app.modules.library.infrastructure.orm import Item as ItemRow
from app.modules.library.infrastructure.orm import ReadingList as ListRow
from app.modules.library.infrastructure.orm import ReadingListItem as ListItemRow
from app.shared.contracts.library import ReadingListSummary

from sqlalchemy import (
    ColumnElement,
    Uuid,
    and_,
    delete,
    func,
    literal,
    or_,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import ARRAY as PG_ARRAY
from sqlalchemy.ext.asyncio import AsyncSession


def names_group(group_id: UUID) -> ColumnElement[bool]:
    """`group_ids @> {group_id}`: the list names the group (uses the GIN index).

    The model declares the generic `ARRAY`, which has no `contains`, so the
    PostgreSQL operator is spelled out.
    """
    return ListRow.group_ids.op("@>", is_comparison=True)(
        literal([group_id], PG_ARRAY(Uuid))
    )


# - - - Row <-> entity - - -


def _list_from(row: ListRow) -> ReadingList:
    return ReadingList(
        id=row.id,
        owner_id=row.owner_id,
        title=row.title,
        scope=ListScope(row.scope),
        status=ListStatus(row.status),
        created_at=row.created_at,
        updated_at=row.updated_at,
        description=row.description,
        subject_id=row.subject_id,
        group_ids=list(row.group_ids),
        year_of_study=row.year_of_study,
        academic_year=row.academic_year,
        term_half=row.term_half,
    )


def _apply_list(row: ListRow, reading_list: ReadingList) -> None:
    row.owner_id = reading_list.owner_id
    row.title = reading_list.title
    row.description = reading_list.description
    row.scope = reading_list.scope.value
    row.subject_id = reading_list.subject_id
    row.group_ids = list(reading_list.group_ids)
    row.year_of_study = reading_list.year_of_study
    row.academic_year = reading_list.academic_year
    row.term_half = reading_list.term_half
    row.status = reading_list.status.value
    row.updated_at = reading_list.updated_at


def _entry_from(row: ListItemRow) -> ReadingListEntry:
    return ReadingListEntry(
        position=row.position,
        importance=Importance(row.importance),
        item_id=row.item_id,
        url=row.url,
        title=row.title,
        page_from=row.page_from,
        page_to=row.page_to,
        week_label=row.week_label,
        due_on=row.due_on,
        topic_id=row.topic_id,
        note=row.note,
    )


def _entry_row(list_id: UUID, entry: ReadingListEntry) -> ListItemRow:
    return ListItemRow(
        list_id=list_id,
        position=entry.position,
        item_id=entry.item_id,
        url=entry.url,
        title=entry.title,
        importance=entry.importance.value,
        page_from=entry.page_from,
        page_to=entry.page_to,
        week_label=entry.week_label,
        due_on=entry.due_on,
        topic_id=entry.topic_id,
        note=entry.note,
    )


class SqlReadingListRepository:
    """Stores reading lists in schema `library`."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to the unit of work's session."""
        self.session = session

    async def lists_for_item(
        self, item_id: UUID, *, group_id: UUID | None, staff: bool
    ) -> list[tuple[UUID, str, Importance]]:
        """Published lists with the item, as `(list id, title, importance)`."""
        query = (
            select(ListRow.id, ListRow.title, ListItemRow.importance)
            .join(ListItemRow, ListItemRow.list_id == ListRow.id)
            .where(
                ListItemRow.item_id == item_id,
                ListRow.status == ListStatus.PUBLISHED.value,
            )
            .order_by(ListRow.title)
        )
        if not staff:
            audience: list[ColumnElement[bool]] = [
                ListRow.scope.in_([ListScope.SCHOOL.value, ListScope.SUBJECT.value])
            ]
            if group_id is not None:
                audience.append(names_group(group_id))
            query = query.where(or_(*audience))
        rows = await self.session.execute(query)
        return [(lid, title, Importance(imp)) for lid, title, imp in rows.all()]

    # - - - Lists - - -

    async def add(self, reading_list: ReadingList) -> None:
        """Insert a list (entries are separate)."""
        row = ListRow(id=reading_list.id, created_at=reading_list.created_at)
        _apply_list(row, reading_list)
        self.session.add(row)
        await self.session.flush()

    async def get(self, list_id: UUID, *, lock: bool = False) -> ReadingList | None:
        """The list or None; `lock` takes a row lock for a change."""
        query = select(ListRow).where(ListRow.id == list_id)
        if lock:
            query = query.with_for_update()
        row = (await self.session.execute(query)).scalar_one_or_none()
        return _list_from(row) if row else None

    async def save(self, reading_list: ReadingList) -> None:
        """Update the fields of a list."""
        row = await self.session.get(ListRow, reading_list.id)
        if row is None:
            raise LookupError(f"reading list {reading_list.id} is not stored")
        _apply_list(row, reading_list)
        await self.session.flush()

    async def delete(self, list_id: UUID) -> None:
        """Delete the list and its entries (cascade)."""
        await self.session.execute(delete(ListRow).where(ListRow.id == list_id))

    async def find(
        self,
        *,
        subject_id: UUID | None = None,
        owner_id: UUID | None = None,
        group_id: UUID | None = None,
        status: ListStatus | None = None,
    ) -> list[ReadingList]:
        """Lists matching every given filter, newest change first."""
        query = select(ListRow).order_by(ListRow.updated_at.desc(), ListRow.id)
        if subject_id is not None:
            query = query.where(ListRow.subject_id == subject_id)
        if owner_id is not None:
            query = query.where(ListRow.owner_id == owner_id)
        if group_id is not None:
            query = query.where(names_group(group_id))
        if status is not None:
            query = query.where(ListRow.status == status.value)
        rows = await self.session.execute(query)
        return [_list_from(row) for row in rows.scalars()]

    # - - - Entries - - -

    async def entries(
        self, list_ids: Sequence[UUID]
    ) -> dict[UUID, list[ReadingListEntry]]:
        """Entries of each list by position (empty lists are absent)."""
        result: dict[UUID, list[ReadingListEntry]] = {}
        if not list_ids:
            return result
        rows = await self.session.execute(
            select(ListItemRow)
            .where(ListItemRow.list_id.in_(set(list_ids)))
            .order_by(ListItemRow.list_id, ListItemRow.position)
        )
        for row in rows.scalars():
            result.setdefault(row.list_id, []).append(_entry_from(row))
        return result

    async def replace_entries(
        self, list_id: UUID, entries: Sequence[ReadingListEntry]
    ) -> None:
        """Replace all entries of the list in one step."""
        await self.session.execute(
            delete(ListItemRow).where(ListItemRow.list_id == list_id)
        )
        self.session.add_all([_entry_row(list_id, entry) for entry in entries])
        await self.session.flush()

    async def clear_topic(self, topic_ids: Collection[UUID]) -> int:
        """Forget the topics on entries (a deleted topic); returns entries changed."""
        if not topic_ids:
            return 0
        rows = await self.session.execute(
            update(ListItemRow)
            .where(ListItemRow.topic_id.in_(set(topic_ids)))
            .values(topic_id=None)
            .returning(ListItemRow.position)
        )
        return len(rows.all())

    # - - - For the subject hub - - -

    async def summaries_for_subject(
        self, subject_id: UUID, *, group_id: UUID | None
    ) -> list[ReadingListSummary]:
        """Published lists of the subject that the group may see, with entry counts."""
        audience: list[ColumnElement[bool]] = [
            ListRow.scope.in_([ListScope.SUBJECT.value, ListScope.SCHOOL.value])
        ]
        if group_id is not None:
            audience.append(
                and_(ListRow.scope == ListScope.GROUPS.value, names_group(group_id))
            )
        listed = or_(
            ListItemRow.item_id.is_(None),
            and_(
                ItemRow.status == ItemStatus.PUBLISHED.value,
                ItemRow.visibility != Visibility.HIDDEN.value,
            ),
        )
        query = (
            select(
                ListRow.id,
                ListRow.title,
                func.count(ListItemRow.position).filter(listed),
                func.count(ListItemRow.position).filter(
                    listed, ListItemRow.importance == Importance.ESSENTIAL.value
                ),
            )
            .select_from(ListRow)
            .outerjoin(ListItemRow, ListItemRow.list_id == ListRow.id)
            .outerjoin(ItemRow, ItemRow.id == ListItemRow.item_id)
            .where(
                ListRow.subject_id == subject_id,
                ListRow.status == ListStatus.PUBLISHED.value,
                or_(*audience),
            )
            .group_by(ListRow.id, ListRow.title)
            .order_by(ListRow.title, ListRow.id)
        )
        rows = await self.session.execute(query)
        return [
            ReadingListSummary(
                id=list_id, title=title, entries=entries, essential_entries=essential
            )
            for list_id, title, entries, essential in rows.all()
        ]
