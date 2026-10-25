"""SQL read model over marks, results and terms (same module, read only)."""

import datetime as dt
from collections.abc import Sequence
from typing import Any
from uuid import UUID

from app.modules.academic.domain.classwork.records import MarkRecord, TermRecord
from app.modules.academic.infrastructure.orm.mark import Mark
from app.modules.academic.infrastructure.orm.result import Result
from app.modules.academic.infrastructure.orm.subject import Subject
from app.modules.academic.infrastructure.orm.term import Term

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession


def _mark_select() -> sa.Select[Any]:
    return sa.select(
        Mark.subject_id,
        Subject.name,
        Subject.short_name,
        Mark.semester,
        Mark.type,
        Mark.value,
        Mark.date,
        Mark.lesson_id,
        Mark.created_at,
    ).join(Subject, Subject.id == Mark.subject_id)


def _mark(row: Any) -> MarkRecord:
    return MarkRecord(
        subject_id=row.subject_id,
        subject_names={str(k): str(v) for k, v in (row.name or {}).items() if v},
        subject_short=row.short_name,
        semester=row.semester,
        type=row.type,
        value=row.value,
        date=row.date,
        lesson_id=row.lesson_id,
        created_at=row.created_at,
    )


def _term(row: Any) -> TermRecord:
    return TermRecord(id=row.id, starts_on=row.starts_on, ends_on=row.ends_on)


class SqlResultsReader:
    """Implements ResultsReader on an open session."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind to the unit of work's session."""
        self.session = session

    async def new_marks(
        self, student_id: UUID, since: dt.datetime | None, limit: int
    ) -> list[MarkRecord]:
        """Marks first seen after a moment, newest first."""
        stmt = _mark_select().where(
            Mark.student_id == student_id, Mark.removed_at.is_(None)
        )
        if since is not None:
            stmt = stmt.where(Mark.created_at > since)
        stmt = stmt.order_by(Mark.created_at.desc(), Mark.date.desc()).limit(limit)
        return [_mark(row) for row in (await self.session.execute(stmt)).all()]

    async def lesson_marks(self, student_id: UUID, lesson_id: UUID) -> list[MarkRecord]:
        """Marks matched to a lesson."""
        stmt = (
            _mark_select()
            .where(
                Mark.student_id == student_id,
                Mark.lesson_id == lesson_id,
                Mark.removed_at.is_(None),
            )
            .order_by(Mark.created_at)
        )
        return [_mark(row) for row in (await self.session.execute(stmt)).all()]

    async def gpas(
        self, student_ids: Sequence[UUID], semester: int
    ) -> dict[UUID, float | None]:
        """Semester GPA per student."""
        if not student_ids:
            return {}
        stmt = sa.select(Result.student_id, Result.value).where(
            Result.student_id.in_(list(student_ids)),
            Result.semester == semester,
            Result.subject_id.is_(None),
        )
        return {
            student_id: None if value is None else float(value)
            for student_id, value in (await self.session.execute(stmt)).all()
        }

    async def current_term(self, today: dt.date) -> TermRecord | None:
        """The term containing the date, else the next one, else the last one."""
        cols = (Term.id, Term.starts_on, Term.ends_on)
        containing = sa.select(*cols).where(
            Term.starts_on <= today, Term.ends_on >= today
        )
        upcoming = (
            sa.select(*cols).where(Term.starts_on > today).order_by(Term.starts_on)
        )
        latest = sa.select(*cols).order_by(Term.ends_on.desc())
        for stmt in (containing, upcoming, latest):
            row = (await self.session.execute(stmt.limit(1))).first()
            if row is not None:
                return _term(row)
        return None

    async def term(self, term_id: UUID) -> TermRecord | None:
        """Return a term by id."""
        stmt = sa.select(Term.id, Term.starts_on, Term.ends_on).where(
            Term.id == term_id
        )
        row = (await self.session.execute(stmt)).first()
        return None if row is None else _term(row)
