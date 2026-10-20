"""SQL read models of work-offs: student list, teacher list, admin list, stats."""

import datetime as dt
from typing import Any
from uuid import UUID

from app.modules.academic.domain.classwork.names import localized
from app.modules.academic.domain.classwork.work_off_views import (
    GroupBy,
    StatRow,
    WorkOffFilter,
    WorkOffView,
)
from app.modules.academic.infrastructure.classwork.work_off_repository import (
    work_off_of,
)
from app.modules.academic.infrastructure.orm.group import Group
from app.modules.academic.infrastructure.orm.lesson import Lesson
from app.modules.academic.infrastructure.orm.student import Student
from app.modules.academic.infrastructure.orm.subject import Subject
from app.modules.academic.infrastructure.orm.work_off import WorkOff

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession


def _view_select() -> sa.Select[Any]:
    return (
        sa.select(
            WorkOff,
            Lesson.date.label("lesson_date"),
            Lesson.period,
            Subject.name.label("subject_names"),
            Lesson.teacher_id.label("lesson_teacher_id"),
            Student.group_id,
            Group.name.label("group_name"),
        )
        .join(Lesson, Lesson.id == WorkOff.lesson_id)
        .join(Subject, Subject.id == Lesson.subject_id)
        .join(Student, Student.user_id == WorkOff.student_id)
        .join(Group, Group.id == Student.group_id)
    )


def _views(rows: Any) -> list[WorkOffView]:
    return [
        WorkOffView(
            work_off=work_off_of(row.WorkOff),
            lesson_date=row.lesson_date,
            period=row.period,
            subject_names={
                str(k): str(v) for k, v in (row.subject_names or {}).items()
            },
            lesson_teacher_id=row.lesson_teacher_id,
            group_id=row.group_id,
            group_name=row.group_name,
        )
        for row in rows
    ]


def _newest_first() -> tuple[Any, ...]:
    return (Lesson.date.desc(), Lesson.period.desc(), WorkOff.id)


def _conditions(flt: WorkOffFilter) -> list[Any]:
    conditions: list[Any] = []
    if flt.start is not None:
        conditions.append(Lesson.date >= flt.start)
    if flt.end is not None:
        conditions.append(Lesson.date <= flt.end)
    if flt.subject_id is not None:
        conditions.append(Lesson.subject_id == flt.subject_id)
    if flt.teacher_id is not None:
        conditions.append(Lesson.teacher_id == flt.teacher_id)
    if flt.group_id is not None:
        conditions.append(Student.group_id == flt.group_id)
    if flt.student_id is not None:
        conditions.append(WorkOff.student_id == flt.student_id)
    if flt.status != "all":
        conditions.append(
            WorkOff.status == ("assigned" if flt.status == "open" else "done")
        )
    return conditions


class SqlWorkOffReader:
    """Implements WorkOffReader on an open session."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind to the unit of work's session."""
        self.session = session

    async def for_student(self, student_id: UUID, open_only: bool) -> list[WorkOffView]:
        """The student's work-offs, newest lesson first."""
        stmt = _view_select().where(WorkOff.student_id == student_id)
        if open_only:
            stmt = stmt.where(WorkOff.status == "assigned")
        rows = (await self.session.execute(stmt.order_by(*_newest_first()))).all()
        return _views(rows)

    async def open_for_teacher(self, teacher_id: UUID) -> list[WorkOffView]:
        """Open work-offs the teacher assigned or whose lesson they teach."""
        stmt = (
            _view_select()
            .where(
                WorkOff.status == "assigned",
                sa.or_(
                    WorkOff.assigned_by == teacher_id, Lesson.teacher_id == teacher_id
                ),
            )
            .order_by(*_newest_first())
        )
        return _views((await self.session.execute(stmt)).all())

    async def admin_list(
        self, flt: WorkOffFilter, limit: int, offset: int
    ) -> tuple[int, list[WorkOffView]]:
        """Filtered page, newest lesson first, and the total count."""
        where = _conditions(flt)
        joined = _view_select().where(*where)
        count = sa.select(sa.func.count()).select_from(joined.subquery())
        total = (await self.session.execute(count)).scalar_one()
        page = joined.order_by(*_newest_first()).limit(limit).offset(offset)
        return int(total), _views((await self.session.execute(page)).all())

    async def stats(
        self, group_by: GroupBy, start: dt.date, end: dt.date
    ) -> list[StatRow]:
        """Open and done counts per key for lessons in the date range."""
        keys: dict[str, Any] = {
            "subject": Lesson.subject_id,
            "teacher": Lesson.teacher_id,
            "group": Student.group_id,
            "student": WorkOff.student_id,
        }
        key = keys[group_by]
        label = {"subject": Subject.name, "group": Group.name}.get(group_by)
        columns = [key.label("key")]
        if label is not None:
            columns.append(label.label("label"))
        stmt = (
            sa.select(
                *columns,
                sa.func.count()
                .filter(WorkOff.status == "assigned")
                .label("open_count"),
                sa.func.count().filter(WorkOff.status == "done").label("done_count"),
            )
            .select_from(WorkOff)
            .join(Lesson, Lesson.id == WorkOff.lesson_id)
            .join(Subject, Subject.id == Lesson.subject_id)
            .join(Student, Student.user_id == WorkOff.student_id)
            .join(Group, Group.id == Student.group_id)
            .where(Lesson.date >= start, Lesson.date <= end, key.is_not(None))
            .group_by(*columns)
        )
        return [
            StatRow(
                key=row.key,
                label=_label(group_by, row),
                open_count=row.open_count,
                done_count=row.done_count,
            )
            for row in (await self.session.execute(stmt)).all()
        ]


def _label(group_by: GroupBy, row: Any) -> str | None:
    if group_by == "subject":
        return localized({str(k): str(v) for k, v in (row.label or {}).items()}, "uz")
    if group_by == "group":
        return str(row.label)
    return None
