"""SQL attendance aggregates over the roster and absent arrays of lessons.

Absences of a student are the lessons whose ``attendance_absent`` contains them;
lessons counted are those whose saved ``attendance_roster`` contains them
(ACA-11, ACA-12). Lessons without a submitted list are counted apart as
``not_taken`` and never as "present".
"""

import datetime as dt
import re
from collections.abc import Sequence
from dataclasses import replace
from typing import Any
from uuid import UUID

from app.modules.academic.application.classwork.ports.attendance_reports import (
    AdminView,
    GroupView,
)
from app.modules.academic.domain.classwork.audience_match import group_keys
from app.modules.academic.domain.classwork.records import (
    ReportRow,
    StudentAttendanceData,
    SubjectStat,
)
from app.modules.academic.infrastructure.classwork.lesson_reader import SqlLessonReader
from app.modules.academic.infrastructure.classwork.sql_helpers import (
    has_uuid,
    overlaps,
)
from app.modules.academic.infrastructure.orm.group import Group
from app.modules.academic.infrastructure.orm.lesson import Lesson as LessonRow
from app.modules.academic.infrastructure.orm.subject import Subject

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

_ENTRY_KEY = {
    "student": "e.student_id",
    "subject": "e.subject_id",
    "day": "e.date",
    "lesson": "e.lesson_id",
    "teacher": "e.teacher_id",
    "group": "e.group_id",
}

_ENTRIES = """
SELECT {key} AS key,
       count(*) FILTER (WHERE e.absent) AS absences,
       count(*) FILTER (WHERE e.absent AND e.excused) AS excused,
       count(*) AS lessons
FROM (
  SELECT l.id AS lesson_id, l.date AS date, l.subject_id AS subject_id,
         l.teacher_id AS teacher_id, u.student_id AS student_id,
         s.group_id AS group_id,
         COALESCE(l.attendance_absent @> ARRAY[u.student_id], false) AS absent,
         COALESCE(
           jsonb_exists(l.attendance_excused, CAST(u.student_id AS text)), false
         ) AS excused
  FROM academic.lessons l
  CROSS JOIN LATERAL unnest(l.attendance_roster) AS u(student_id)
  LEFT JOIN academic.students s ON s.user_id = u.student_id
  WHERE l.status = 'scheduled' AND l.attendance_roster IS NOT NULL
    AND l.date >= :start AND l.date <= :end
) e
WHERE {where}
GROUP BY 1
"""

_NOT_TAKEN_BASE = (
    "l.status = 'scheduled' AND l.attendance_absent IS NULL "
    "AND l.starts_at < :now AND l.date >= :start AND l.date <= :end"
)

_NOT_TAKEN_SIMPLE = (
    "SELECT {key} AS key, count(*) AS n FROM academic.lessons l "
    "WHERE {base} {extra} GROUP BY 1"
)

_NOT_TAKEN_GROUP = (
    "SELECT CAST(split_part(a.k, chr(58), 1) AS uuid) AS key, "
    "count(DISTINCT l.id) AS n FROM academic.lessons l "
    "CROSS JOIN LATERAL unnest(l.audience) AS a(k) WHERE {base} GROUP BY 1"
)

_NOT_TAKEN_STUDENT = (
    "SELECT s.user_id AS key, count(*) AS n FROM academic.students s "
    "JOIN academic.lessons l ON l.audience && CASE WHEN s.subgroup IS NULL THEN "
    "ARRAY[CAST(s.group_id AS text), CAST(s.group_id AS text) || chr(58) || '1', "
    "CAST(s.group_id AS text) || chr(58) || '2'] ELSE ARRAY[CAST(s.group_id AS text), "
    "CAST(s.group_id AS text) || chr(58) || CAST(s.subgroup AS text)] END "
    "WHERE s.status = 'active' AND {base} {extra} GROUP BY 1"
)

_SIMPLE_KEYS = {
    "subject": ("l.subject_id", ""),
    "teacher": ("l.teacher_id", "AND l.teacher_id IS NOT NULL"),
    "day": ("l.date", ""),
    "lesson": ("l.id", ""),
}

_PARAM_TYPES: dict[str, Any] = {
    "start": sa.Date,
    "end": sa.Date,
    "now": sa.DateTime(timezone=True),
    "group": sa.Uuid,
    "group_keys": sa.ARRAY(sa.Text),
}


def _statement(
    sql: str, params: dict[str, Any]
) -> tuple[sa.TextClause, dict[str, Any]]:
    """Bind only the parameters the SQL mentions, with their types."""
    used = {
        name: value for name, value in params.items() if re.search(rf":{name}\b", sql)
    }
    binds = [sa.bindparam(name, type_=_PARAM_TYPES[name]) for name in used]
    return sa.text(sql).bindparams(*binds), used


def _text_key(value: Any) -> str:
    return value.isoformat() if isinstance(value, dt.date) else str(value)


class SqlAttendanceReports:
    """Implements AttendanceReports on an open session."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind to the unit of work's session."""
        self.session = session

    async def _pairs(self, sql: str, params: dict[str, Any]) -> list[Any]:
        stmt, used = _statement(sql, params)
        return list((await self.session.execute(stmt, used)).all())

    # - - - Student's own page - - -

    async def student_attendance(
        self,
        student_id: UUID,
        keys: Sequence[str],
        start: dt.date,
        end: dt.date,
        now: dt.datetime,
    ) -> StudentAttendanceData:
        """A student's own absences per subject, per day and the missed lessons."""
        absent = has_uuid(LessonRow.attendance_absent, student_id)
        in_roster = has_uuid(LessonRow.attendance_roster, student_id)
        taken = sa.and_(
            LessonRow.status == "scheduled",
            LessonRow.date >= start,
            LessonRow.date <= end,
        )
        excused = sa.and_(
            absent, sa.func.jsonb_exists(LessonRow.attendance_excused, str(student_id))
        )
        per_subject = (
            sa.select(
                LessonRow.subject_id,
                Subject.name,
                Subject.short_name,
                sa.func.count().label("lessons"),
                sa.func.count().filter(absent).label("absences"),
                sa.func.count().filter(excused).label("excused"),
            )
            .join(Subject, Subject.id == LessonRow.subject_id)
            .where(taken, in_roster)
            .group_by(LessonRow.subject_id, Subject.name, Subject.short_name)
        )
        per_day = (
            sa.select(LessonRow.date, sa.func.count())
            .where(taken, absent)
            .group_by(LessonRow.date)
            .order_by(LessonRow.date)
        )
        not_taken = sa.select(sa.func.count()).where(
            taken,
            overlaps(LessonRow.audience, keys),
            LessonRow.attendance_absent.is_(None),
            LessonRow.starts_at < now,
        )
        data = StudentAttendanceData()
        for row in (await self.session.execute(per_subject)).all():
            data.subjects.append(
                SubjectStat(
                    subject_id=row.subject_id,
                    names={k: str(v) for k, v in (row.name or {}).items() if v},
                    short=row.short_name,
                    absences=row.absences,
                    excused=row.excused,
                    lessons=row.lessons,
                )
            )
        data.days = [
            (day, count) for day, count in (await self.session.execute(per_day)).all()
        ]
        data.not_taken = int((await self.session.execute(not_taken)).scalar_one())
        data.missed = await SqlLessonReader(self.session).student_absences(
            student_id, start, end
        )
        return data

    async def absence_count(
        self, student_id: UUID, start: dt.date, end: dt.date
    ) -> int:
        """Number of lessons the student was absent from between two dates."""
        stmt = sa.select(sa.func.count()).where(
            LessonRow.status == "scheduled",
            LessonRow.date >= start,
            LessonRow.date <= end,
            has_uuid(LessonRow.attendance_absent, student_id),
        )
        return int((await self.session.execute(stmt)).scalar_one())

    # - - - Group and admin reports - - -

    async def group_report(
        self,
        group_id: UUID,
        view: GroupView,
        start: dt.date,
        end: dt.date,
        now: dt.datetime,
    ) -> list[ReportRow]:
        """The curator's view of one group."""
        return await self._report(view, start, end, group_id, now)

    async def admin_report(
        self,
        view: AdminView,
        start: dt.date,
        end: dt.date,
        group_id: UUID | None,
        now: dt.datetime,
    ) -> list[ReportRow]:
        """The Administration's view."""
        return await self._report(view, start, end, group_id, now)

    async def _report(
        self,
        view: str,
        start: dt.date,
        end: dt.date,
        group_id: UUID | None,
        now: dt.datetime,
    ) -> list[ReportRow]:
        params: dict[str, Any] = {"start": start, "end": end, "now": now}
        if group_id is not None:
            params["group"] = group_id
            params["group_keys"] = group_keys(group_id)
        entries = await self._entries(view, params, group_id is not None)
        not_taken = await self._not_taken(view, params, group_id)
        rows = [
            ReportRow(
                key=key,
                absences=entries.get(key, (0, 0, 0))[0],
                excused=entries.get(key, (0, 0, 0))[1],
                lessons=entries.get(key, (0, 0, 0))[2],
                not_taken=not_taken.get(key, 0),
            )
            for key in sorted(set(entries) | set(not_taken))
        ]
        return await self._label(view, rows)

    async def _entries(
        self, view: str, params: dict[str, Any], by_group: bool
    ) -> dict[str, tuple[int, int, int]]:
        conditions = ["TRUE"]
        if by_group:
            conditions.append("e.group_id = :group")
        if view == "group":
            conditions.append("e.group_id IS NOT NULL")
        sql = _ENTRIES.format(key=_ENTRY_KEY[view], where=" AND ".join(conditions))
        return {
            _text_key(row.key): (row.absences, row.excused, row.lessons)
            for row in await self._pairs(sql, params)
        }

    async def _not_taken(
        self, view: str, params: dict[str, Any], group_id: UUID | None
    ) -> dict[str, int]:
        if view == "group":
            sql = _NOT_TAKEN_GROUP.format(base=_NOT_TAKEN_BASE)
        elif view == "student":
            extra = "AND s.group_id = :group" if group_id else ""
            sql = _NOT_TAKEN_STUDENT.format(base=_NOT_TAKEN_BASE, extra=extra)
        else:
            key, extra = _SIMPLE_KEYS[view]
            if group_id is not None:
                extra += " AND l.audience && :group_keys"
            sql = _NOT_TAKEN_SIMPLE.format(key=key, base=_NOT_TAKEN_BASE, extra=extra)
        counted = {
            _text_key(row.key): int(row.n) for row in await self._pairs(sql, params)
        }
        if view == "group" and group_id is not None:
            return {k: v for k, v in counted.items() if k == str(group_id)}
        return counted

    async def _label(self, view: str, rows: list[ReportRow]) -> list[ReportRow]:
        """Attach display data: subject and group names, lesson and day details."""
        if not rows:
            return rows
        if view == "subject":
            return await self._label_subjects(rows)
        if view == "group":
            return await self._label_groups(rows)
        if view == "lesson":
            return await self._label_lessons(rows)
        if view == "day":
            return [replace(row, on=dt.date.fromisoformat(row.key)) for row in rows]
        return rows

    async def _label_subjects(self, rows: list[ReportRow]) -> list[ReportRow]:
        found = await self.session.execute(
            sa.select(Subject.id, Subject.name).where(
                Subject.id.in_([UUID(row.key) for row in rows])
            )
        )
        names = {str(sid): _names(name) for sid, name in found.all()}
        return [replace(row, names=names.get(row.key)) for row in rows]

    async def _label_groups(self, rows: list[ReportRow]) -> list[ReportRow]:
        found = await self.session.execute(
            sa.select(Group.id, Group.name).where(
                Group.id.in_([UUID(row.key) for row in rows])
            )
        )
        texts = {str(gid): name for gid, name in found.all()}
        return [replace(row, text=texts.get(row.key)) for row in rows]

    async def _label_lessons(self, rows: list[ReportRow]) -> list[ReportRow]:
        found = await self.session.execute(
            sa.select(LessonRow.id, LessonRow.date, LessonRow.period, Subject.name)
            .join(Subject, Subject.id == LessonRow.subject_id)
            .where(LessonRow.id.in_([UUID(row.key) for row in rows]))
        )
        info = {
            str(lid): (day, period, _names(name)) for lid, day, period, name in found
        }
        labelled: list[ReportRow] = []
        for row in rows:
            day, period, names = info.get(row.key, (None, None, None))
            labelled.append(replace(row, on=day, period=period, names=names))
        return labelled


def _names(raw: Any) -> dict[str, str]:
    return {str(k): str(v) for k, v in (raw or {}).items() if v}
