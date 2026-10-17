"""MarksQueries: read access to marks and results for other modules."""

import datetime as dt
from collections.abc import Sequence
from typing import Any
from uuid import UUID

from app.modules.academic.application.marks.ports.unit_of_work import MarksUowFactory
from app.modules.academic.application.marks.semester_range import semester_range
from app.modules.academic.application.marks.view_context import (
    ViewContext,
    build_context,
    caller_locale,
    num,
)
from app.modules.academic.domain.marks.read_models import MarkRow
from app.modules.academic.domain.marks.semesters import resolve_semester
from app.shared.clock import Clock, local_today
from app.shared.contracts.academic import MarkRef, SubjectSummary
from app.shared.contracts.identity import IdentityDirectory


class MarksQueriesImpl:
    """Implements the `MarksQueries` contract."""

    def __init__(
        self, *, uow_factory: MarksUowFactory, identity: IdentityDirectory, clock: Clock
    ) -> None:
        """Store collaborators."""
        self._uow_factory = uow_factory
        self._identity = identity
        self._clock = clock

    async def subjects_summary(
        self, user_id: UUID, semester: int | None
    ) -> list[SubjectSummary]:
        """Return the student's standing per subject (default: current semester)."""
        locale = await caller_locale(self._identity, user_id)
        async with self._uow_factory() as uow:
            reader = uow.reader
            ctx = await reader.student_context(user_id)
            if ctx is None:
                return []
            results = await reader.results(user_id, None)
            sem = resolve_semester(
                semester, ctx.current_semester, {r.semester for r in results}
            )
            rows = {
                r.subject_id: r
                for r in results
                if r.semester == sem and r.subject_id is not None
            }
            subject_ids = set(rows) | set(ctx.curriculum_subject_ids)
            rng = await semester_range(reader, ctx, sem, local_today(self._clock))
            counts = (
                {}
                if rng is None
                else await reader.attendance_counts(user_id, *rng, semester=sem)
            )
            teachers = (
                {} if rng is None else await reader.teacher_ids(ctx, subject_ids, *rng)
            )
            view = await build_context(
                reader,
                self._identity,
                locale=locale,
                subject_ids=subject_ids,
                user_ids={t for ids in teachers.values() for t in ids},
            )
        summaries = []
        for sid in subject_ids:
            row, count = rows.get(sid), counts.get(sid)
            summaries.append(
                SubjectSummary(
                    subject_id=sid,
                    name=view.subject_name(sid),
                    teacher_names=_names(view, teachers.get(sid, [])),
                    semester_mark=None if row is None else num(row.value),
                    emis_rating=None if row is None else row.emis_rating,
                    absences=0 if count is None else count.absences,
                    lessons_with_attendance=(
                        0 if count is None else count.with_attendance
                    ),
                )
            )
        return sorted(summaries, key=lambda s: s.name.casefold())

    async def marks(
        self,
        user_id: UUID,
        subject_id: UUID | None,
        start: dt.date | None,
        end: dt.date | None,
    ) -> list[MarkRef]:
        """Return the student's marks of every semester, newest first."""
        async with self._uow_factory() as uow:
            rows = await uow.reader.marks(
                user_id, subject_id=subject_id, start=start, end=end
            )
            return await self._refs(uow.reader, user_id, rows)

    async def new_marks_since(
        self, user_id: UUID, since: dt.datetime | None, limit: int = 20
    ) -> list[MarkRef]:
        """Return marks the sync first saw after a moment, newest first."""
        async with self._uow_factory() as uow:
            rows = await uow.reader.new_marks(user_id, since, limit)
            return await self._refs(uow.reader, user_id, rows)

    async def results(self, user_id: UUID, semester: int | None) -> dict[str, Any]:
        """Return the semester GPA and the result of each subject."""
        locale = await caller_locale(self._identity, user_id)
        async with self._uow_factory() as uow:
            ctx = await uow.reader.student_context(user_id)
            if ctx is None:
                return {"semester": semester, "gpa": None, "subjects": []}
            all_rows = await uow.reader.results(user_id, None)
            sem = resolve_semester(
                semester, ctx.current_semester, {r.semester for r in all_rows}
            )
            rows = [r for r in all_rows if r.semester == sem]
            view = await build_context(
                uow.reader,
                self._identity,
                locale=locale,
                subject_ids={r.subject_id for r in rows if r.subject_id},
            )
        subjects = [
            {
                "subject_id": r.subject_id,
                "name": view.subject_name(r.subject_id),
                "lesson_avg": num(r.lesson_avg),
                "midterm_avg": num(r.midterm_avg),
                "final_avg": num(r.final_avg),
                "semester_mark": num(r.value),
                "emis_rating": r.emis_rating,
                "marks_count": r.marks_count,
            }
            for r in rows
            if r.subject_id is not None
        ]
        subjects.sort(key=lambda s: str(s["name"]).casefold())
        gpa = next((r.value for r in rows if r.subject_id is None), None)
        return {"semester": sem, "gpa": num(gpa), "subjects": subjects}

    async def gpa_for_users(
        self, user_ids: Sequence[UUID], semester: int | None
    ) -> dict[UUID, float | None]:
        """Return the GPA of each user (their current semester when None)."""
        async with self._uow_factory() as uow:
            values = await uow.reader.gpa_values(user_ids, semester)
        return {uid: num(values.get(uid)) for uid in user_ids}

    async def _refs(
        self, reader: Any, user_id: UUID, rows: Sequence[MarkRow]
    ) -> list[MarkRef]:
        locale = await caller_locale(self._identity, user_id)
        view = await build_context(
            reader,
            self._identity,
            locale=locale,
            subject_ids={r.subject_id for r in rows},
        )
        return [
            MarkRef(
                subject_id=r.subject_id,
                subject_name=view.subject_name(r.subject_id),
                semester=r.semester,
                type=r.type,
                value=r.value,
                date=r.date,
                lesson_id=r.lesson_id,
            )
            for r in rows
        ]


def _names(view: ViewContext, teacher_ids: Sequence[UUID]) -> tuple[str, ...]:
    people = (view.person(t) for t in teacher_ids)
    return tuple(
        f"{p['first_name']} {p['last_name']}".strip() for p in people if p is not None
    )
