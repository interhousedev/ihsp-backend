"""SQL repository of notebooks."""

from collections.abc import Sequence
from datetime import datetime
from typing import Any, cast
from uuid import UUID

from app.modules.notebooks.domain.entities import (
    AutoSettings,
    ChatConfig,
    Notebook,
    NotebookSummary,
)
from app.modules.notebooks.domain.enums import (
    NotebookOrigin,
    SourceStatus,
    SummaryStatus,
)
from app.modules.notebooks.infrastructure.orm.notebook import Notebook as NotebookRow
from app.modules.notebooks.infrastructure.orm.source import Source as SourceRow
from app.modules.notebooks.ports.notebook_repository import NotebookCursor

from sqlalchemy import (
    ColumnElement,
    CursorResult,
    Select,
    and_,
    delete,
    false,
    func,
    or_,
    select,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

_USABLE = [SourceStatus.READY.value, SourceStatus.STALE.value]
_MANUAL = NotebookOrigin.MANUAL.value
_COURSE = NotebookOrigin.COURSE.value
# Subject and lesson notebooks; manual notebooks and course workspaces are not auto.
_AUTO = [NotebookOrigin.SUBJECT_AUTO.value, NotebookOrigin.LESSON_AUTO.value]


def _count_sources(*conditions: ColumnElement[bool]) -> ColumnElement[int]:
    """A correlated subquery: how many of the notebook's sources match."""
    return (
        select(func.count(SourceRow.id))
        .where(SourceRow.notebook_id == NotebookRow.id, *conditions)
        .correlate(NotebookRow)
        .scalar_subquery()
    )


def _select_notebooks() -> Select[tuple[NotebookRow, int, int]]:
    """Notebook rows with their ready (usable) and selected-and-ready source counts."""
    ready = SourceRow.status.in_(_USABLE)
    return select(
        NotebookRow,
        _count_sources(ready).label("ready_source_count"),
        _count_sources(ready, SourceRow.selected.is_(True)).label(
            "selected_source_count"
        ),
    )


def _to_entity(row: NotebookRow, ready: int, selected: int) -> Notebook:
    return Notebook(
        id=row.id,
        owner_id=row.owner_id,
        title=row.title,
        created_at=row.created_at,
        updated_at=row.updated_at,
        title_auto=row.title_auto,
        emoji=row.emoji,
        emoji_auto=row.emoji_auto,
        pinned=row.pinned,
        chat_config=ChatConfig.model_validate(row.chat_config),
        summary=(
            NotebookSummary.model_validate(row.summary)
            if row.summary is not None
            else None
        ),
        summary_status=SummaryStatus(row.summary_status),
        summary_due_at=row.summary_due_at,
        summary_hash=row.summary_hash,
        source_count=int(row.source_count),
        char_count=int(row.char_count),
        last_opened_at=row.last_opened_at,
        deleted_at=row.deleted_at,
        origin=NotebookOrigin(row.origin),
        subject_id=row.subject_id,
        lesson_id=row.lesson_id,
        auto_settings=(
            AutoSettings.model_validate(row.auto_settings)
            if row.auto_settings is not None
            else None
        ),
        auto_synced_at=row.auto_synced_at,
        space_key=row.space_key,
        course_id=row.course_id,
        ready_source_count=int(ready),
        selected_source_count=int(selected),
    )


def _apply(row: NotebookRow, notebook: Notebook) -> None:
    row.owner_id = notebook.owner_id
    row.title = notebook.title
    row.title_auto = notebook.title_auto
    row.emoji = notebook.emoji
    row.emoji_auto = notebook.emoji_auto
    row.pinned = notebook.pinned
    row.chat_config = notebook.chat_config.model_dump(mode="json")
    row.summary = (
        notebook.summary.model_dump(mode="json")
        if notebook.summary is not None
        else None
    )
    row.summary_status = notebook.summary_status.value
    row.summary_due_at = notebook.summary_due_at
    row.summary_hash = notebook.summary_hash
    row.source_count = notebook.source_count
    row.char_count = notebook.char_count
    row.last_opened_at = notebook.last_opened_at
    row.deleted_at = notebook.deleted_at
    row.origin = notebook.origin.value
    row.subject_id = notebook.subject_id
    row.lesson_id = notebook.lesson_id
    row.auto_settings = (
        notebook.auto_settings.model_dump(mode="json")
        if notebook.auto_settings is not None
        else None
    )
    row.auto_synced_at = notebook.auto_synced_at
    row.space_key = notebook.space_key
    row.course_id = notebook.course_id
    row.created_at = notebook.created_at
    row.updated_at = notebook.updated_at


def _after(cursor: NotebookCursor) -> ColumnElement[bool]:
    """Rows after the cursor (pinned, last_opened nulls last, id; all descending)."""
    later_pin = NotebookRow.pinned.is_(False) if cursor.pinned else false()
    opened = cursor.last_opened_at
    if opened is None:
        within = and_(NotebookRow.last_opened_at.is_(None), NotebookRow.id < cursor.id)
    else:
        within = or_(
            NotebookRow.last_opened_at < opened,
            NotebookRow.last_opened_at.is_(None),
            and_(NotebookRow.last_opened_at == opened, NotebookRow.id < cursor.id),
        )
    return or_(later_pin, and_(NotebookRow.pinned == cursor.pinned, within))


class SqlNotebookRepository:
    """Notebooks in `notebooks.notebooks`."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to the unit of work's session."""
        self.session = session

    async def add(self, notebook: Notebook) -> None:
        """Insert a new notebook."""
        row = NotebookRow(id=notebook.id)
        _apply(row, notebook)
        self.session.add(row)
        await self.session.flush()

    async def _row(self, notebook_id: UUID) -> NotebookRow | None:
        stmt = select(NotebookRow).where(NotebookRow.id == notebook_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def _entities(
        self, stmt: Select[tuple[NotebookRow, int, int]]
    ) -> list[Notebook]:
        stmt = stmt.execution_options(populate_existing=True)
        result = await self.session.execute(stmt)
        return [_to_entity(row, ready, picked) for row, ready, picked in result.all()]

    async def get(self, notebook_id: UUID) -> Notebook | None:
        """Return the notebook (deleted or not) with its source counts."""
        stmt = _select_notebooks().where(NotebookRow.id == notebook_id)
        found = await self._entities(stmt)
        return found[0] if found else None

    async def get_for_update(self, notebook_id: UUID) -> Notebook | None:
        """Return the notebook and lock its row until the transaction ends."""
        stmt = (
            _select_notebooks()
            .where(NotebookRow.id == notebook_id)
            .with_for_update(of=NotebookRow)
        )
        found = await self._entities(stmt)
        return found[0] if found else None

    async def save(self, notebook: Notebook) -> None:
        """Write the notebook's stored fields, `updated_at` exactly as given.

        An unchanged `updated_at` is written too, so the column's `onupdate` does not
        replace it with the database time (opening a notebook is not an edit).
        """
        row = await self._row(notebook.id)
        if row is None:
            return
        _apply(row, notebook)
        flag_modified(row, "updated_at")
        await self.session.flush()

    async def count_live(self, owner_id: UUID) -> int:
        """Return how many non-deleted notebooks the owner wrote themselves."""
        return await self._count_live(owner_id, NotebookRow.origin == _MANUAL)

    async def count_live_auto(self, owner_id: UUID) -> int:
        """Return how many non-deleted subject and lesson notebooks the owner has."""
        return await self._count_live(owner_id, NotebookRow.origin.in_(_AUTO))

    async def _count_live(self, owner_id: UUID, kind: ColumnElement[bool]) -> int:
        stmt = select(func.count(NotebookRow.id)).where(
            NotebookRow.owner_id == owner_id, NotebookRow.deleted_at.is_(None), kind
        )
        return int((await self.session.execute(stmt)).scalar_one())

    async def find_auto(
        self, owner_id: UUID, origin: NotebookOrigin, target_id: UUID
    ) -> Notebook | None:
        """The owner's live subject notebook (`target_id` = subject) or lesson one."""
        target = (
            NotebookRow.subject_id
            if origin is NotebookOrigin.SUBJECT_AUTO
            else NotebookRow.lesson_id
        )
        stmt = _select_notebooks().where(
            NotebookRow.owner_id == owner_id,
            NotebookRow.origin == origin.value,
            target == target_id,
            NotebookRow.deleted_at.is_(None),
        )
        found = await self._entities(stmt)
        return found[0] if found else None

    async def add_auto(self, notebook: Notebook) -> bool:
        """Insert an auto notebook unless the owner already has a live one for it.

        Two requests that open the same subject at once both reach here; the unique
        index lets one in and this returns False for the other (rolled back to a
        savepoint, so the transaction stays usable).
        """
        return await self._add_unique(notebook)

    async def add_workspace(self, notebook: Notebook) -> bool:
        """Insert a course workspace unless the course already has a live one.

        The unique index on the course decides between two first openings at once;
        the loser gets False (a savepoint is rolled back) and reads the winner.
        """
        return await self._add_unique(notebook)

    async def _add_unique(self, notebook: Notebook) -> bool:
        """Insert under a savepoint; False when a unique index refuses the row."""
        row = NotebookRow(id=notebook.id)
        _apply(row, notebook)
        try:
            async with self.session.begin_nested():
                self.session.add(row)
        except IntegrityError:
            return False
        return True

    async def auto_ids_for_lesson(
        self, subject_id: UUID, lesson_id: UUID, limit: int
    ) -> list[UUID]:
        """Live notebooks that feed on a lesson: its subject's and its own.

        Subject notebooks of the lesson's subject, and lesson notebooks of the lesson.
        """
        stmt = (
            select(NotebookRow.id)
            .where(
                NotebookRow.deleted_at.is_(None),
                or_(
                    and_(
                        NotebookRow.origin == NotebookOrigin.SUBJECT_AUTO.value,
                        NotebookRow.subject_id == subject_id,
                    ),
                    and_(
                        NotebookRow.origin == NotebookOrigin.LESSON_AUTO.value,
                        NotebookRow.lesson_id == lesson_id,
                    ),
                ),
            )
            .order_by(NotebookRow.id)
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def due_auto_sync(
        self, synced_before: datetime, opened_after: datetime, limit: int
    ) -> list[UUID]:
        """Live auto notebooks opened lately and not synced since the cutoff.

        Never-synced ones come first, then the longest waiting.
        """
        stmt = (
            select(NotebookRow.id)
            .where(
                NotebookRow.origin.in_(_AUTO),
                NotebookRow.deleted_at.is_(None),
                NotebookRow.last_opened_at >= opened_after,
                or_(
                    NotebookRow.auto_synced_at.is_(None),
                    NotebookRow.auto_synced_at < synced_before,
                ),
            )
            .order_by(NotebookRow.auto_synced_at.asc().nulls_first(), NotebookRow.id)
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_for_owner(
        self,
        owner_id: UUID,
        *,
        query: str | None,
        after: NotebookCursor | None,
        limit: int,
        origin: NotebookOrigin | None = None,
    ) -> list[Notebook]:
        """Live notebooks: pinned first, then `last_opened_at` desc (nulls last).

        Ties are broken by id, newest first. `query` filters by title
        (case-insensitive substring). Course workspaces are not listed (they belong
        to a course, not to the person who opened them first).
        """
        stmt = _select_notebooks().where(
            NotebookRow.owner_id == owner_id,
            NotebookRow.deleted_at.is_(None),
            NotebookRow.origin != _COURSE,
        )
        if origin is not None:
            stmt = stmt.where(NotebookRow.origin == origin.value)
        if query:
            stmt = stmt.where(NotebookRow.title.icontains(query, autoescape=True))
        if after is not None:
            stmt = stmt.where(_after(after))
        stmt = stmt.order_by(
            NotebookRow.pinned.desc(),
            NotebookRow.last_opened_at.desc().nulls_last(),
            NotebookRow.id.desc(),
        ).limit(limit)
        return await self._entities(stmt)

    async def due_summaries(self, now: datetime, limit: int) -> list[Notebook]:
        """Live notebooks with `summary_status='stale'` and `summary_due_at <= now`.

        Rows are locked with `FOR UPDATE SKIP LOCKED` until the transaction ends;
        the most overdue come first. Soft-deleted notebooks are left out.
        """
        stmt = (
            _select_notebooks()
            .where(
                NotebookRow.summary_status == SummaryStatus.STALE.value,
                NotebookRow.summary_due_at <= now,
                NotebookRow.deleted_at.is_(None),
            )
            .order_by(NotebookRow.summary_due_at, NotebookRow.id)
            .limit(limit)
            .with_for_update(skip_locked=True, of=NotebookRow)
        )
        return await self._entities(stmt)

    async def stuck_summaries(
        self, updated_before: datetime, limit: int
    ) -> list[Notebook]:
        """Live notebooks whose summary has been `building` since before the cutoff.

        Rows are locked with `FOR UPDATE SKIP LOCKED` until the transaction ends;
        the longest stuck come first. Soft-deleted notebooks are left out.
        """
        stmt = (
            _select_notebooks()
            .where(
                NotebookRow.summary_status == SummaryStatus.BUILDING.value,
                NotebookRow.updated_at < updated_before,
                NotebookRow.deleted_at.is_(None),
            )
            .order_by(NotebookRow.updated_at, NotebookRow.id)
            .limit(limit)
            .with_for_update(skip_locked=True, of=NotebookRow)
        )
        return await self._entities(stmt)

    async def deleted_before(self, cutoff: datetime, limit: int) -> list[UUID]:
        """Ids of notebooks soft-deleted before the cutoff (oldest first)."""
        stmt = (
            select(NotebookRow.id)
            .where(NotebookRow.deleted_at < cutoff)
            .order_by(NotebookRow.deleted_at, NotebookRow.id)
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def find_course_student(
        self, owner_id: UUID, course_id: UUID
    ) -> Notebook | None:
        """The student's live notebook of an LMS course, if they have one."""
        stmt = _select_notebooks().where(
            NotebookRow.owner_id == owner_id,
            NotebookRow.course_id == course_id,
            NotebookRow.origin == NotebookOrigin.COURSE_STUDENT.value,
            NotebookRow.deleted_at.is_(None),
        )
        found = await self._entities(stmt)
        return found[0] if found else None

    async def add_course_student(self, notebook: Notebook) -> bool:
        """Insert a student's course notebook unless they already have a live one."""
        return await self._add_unique(notebook)

    async def course_student_ids(self, course_id: UUID, limit: int) -> list[UUID]:
        """Live student notebooks of a course (for the sync after a new revision)."""
        stmt = (
            select(NotebookRow.id)
            .where(
                NotebookRow.course_id == course_id,
                NotebookRow.origin == NotebookOrigin.COURSE_STUDENT.value,
                NotebookRow.deleted_at.is_(None),
            )
            .order_by(NotebookRow.id)
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def get_by_course(self, course_id: UUID) -> Notebook | None:
        """Return the live workspace of an LMS course, if it has one."""
        stmt = _select_notebooks().where(
            NotebookRow.course_id == course_id,
            NotebookRow.origin == _COURSE,
            NotebookRow.deleted_at.is_(None),
        )
        found = await self._entities(stmt)
        return found[0] if found else None

    async def ids_for_owner(self, owner_id: UUID) -> list[UUID]:
        """Ids of the owner's own notebooks, deleted or not.

        Course workspaces are left out: they belong to the course and stay when the
        staff member who opened them first is removed.
        """
        stmt = (
            select(NotebookRow.id)
            .where(NotebookRow.owner_id == owner_id, NotebookRow.origin != _COURSE)
            .order_by(NotebookRow.id)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def hard_delete(self, notebook_ids: Sequence[UUID]) -> int:
        """Delete notebooks; sources, passages, messages and outputs cascade."""
        if not notebook_ids:
            return 0
        stmt = delete(NotebookRow).where(NotebookRow.id.in_(notebook_ids))
        result = await self.session.execute(
            stmt, execution_options={"synchronize_session": False}
        )
        return int(cast("CursorResult[Any]", result).rowcount)
