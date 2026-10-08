"""The semester grade table with GPA (WEB-12, WEB-16)."""

from typing import Any

from app.modules.academic.application.marks.ports.unit_of_work import MarksUowFactory
from app.modules.academic.application.marks.view_context import (
    build_context,
    caller_locale,
    num,
)
from app.modules.academic.domain.marks.errors import StudentNotFoundError
from app.modules.academic.domain.marks.semesters import resolve_semester
from app.shared.actor import Actor
from app.shared.contracts.identity import IdentityDirectory


class GetSemesterGrades:
    """Builds `SemesterGrades` for a semester (default: the current one)."""

    def __init__(
        self, *, uow_factory: MarksUowFactory, identity: IdentityDirectory
    ) -> None:
        """Store collaborators."""
        self._uow_factory = uow_factory
        self._identity = identity

    async def execute(self, actor: Actor, semester: int | None) -> dict[str, Any]:
        """Return `SemesterGrades`."""
        locale = await caller_locale(self._identity, actor.user_id)
        async with self._uow_factory() as uow:
            ctx = await uow.reader.student_context(actor.user_id)
            if ctx is None:
                raise StudentNotFoundError()
            results = await uow.reader.results(actor.user_id, None)
            sem = resolve_semester(
                semester, ctx.current_semester, {r.semester for r in results}
            )
            in_semester = [r for r in results if r.semester == sem]
            rows = {r.subject_id: r for r in in_semester if r.subject_id is not None}
            gpa = next((r.value for r in in_semester if r.subject_id is None), None)
            subject_ids = set(rows)
            if sem == ctx.current_semester:
                subject_ids |= set(ctx.curriculum_subject_ids)
            view = await build_context(
                uow.reader, self._identity, locale=locale, subject_ids=subject_ids
            )
        table: list[dict[str, Any]] = []
        for subject_id in subject_ids:
            row = rows.get(subject_id)
            table.append(
                {
                    "subject": view.subject_ref(subject_id),
                    "lesson_avg": None if row is None else num(row.lesson_avg),
                    "midterm_avg": None if row is None else num(row.midterm_avg),
                    "final_avg": None if row is None else num(row.final_avg),
                    "semester_mark": None if row is None else num(row.value),
                    "emis_rating": None if row is None else row.emis_rating,
                    "marks_count": 0 if row is None else row.marks_count,
                }
            )
        table.sort(key=lambda r: str(r["subject"]["name"]).casefold())
        return {
            "semester": sem,
            "gpa": num(gpa),
            "synced_at": ctx.synced_at,
            "rows": table,
        }
