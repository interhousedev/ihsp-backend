"""The student's subjects of a semester with marks, absences and next lesson (WEB-7)."""

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
from app.modules.academic.domain.marks.errors import StudentNotFoundError
from app.modules.academic.domain.marks.read_models import (
    AttendanceCount,
    LessonRow,
    ResultRow,
)
from app.modules.academic.domain.marks.semesters import resolve_semester
from app.shared.actor import Actor
from app.shared.clock import Clock, local_today
from app.shared.contracts.identity import IdentityDirectory


class ListSubjects:
    """Builds the `SubjectCard` list of a semester."""

    def __init__(
        self, *, uow_factory: MarksUowFactory, identity: IdentityDirectory, clock: Clock
    ) -> None:
        """Store collaborators."""
        self._uow_factory = uow_factory
        self._identity = identity
        self._clock = clock

    async def execute(self, actor: Actor, semester: int | None) -> list[dict[str, Any]]:
        """Return `SubjectCard[]` for the semester (default: the current one)."""
        locale = await caller_locale(self._identity, actor.user_id)
        async with self._uow_factory() as uow:
            reader = uow.reader
            ctx = await reader.student_context(actor.user_id)
            if ctx is None:
                raise StudentNotFoundError()
            results = await reader.results(actor.user_id, None)
            sem = resolve_semester(
                semester, ctx.current_semester, {r.semester for r in results}
            )
            rows = {
                r.subject_id: r
                for r in results
                if r.semester == sem and r.subject_id is not None
            }
            current = sem == ctx.current_semester
            subject_ids = set(rows) | (
                set(ctx.curriculum_subject_ids) if current else set()
            )
            rng = await semester_range(reader, ctx, sem, local_today(self._clock))
            counts = (
                {}
                if rng is None
                else await reader.attendance_counts(actor.user_id, *rng)
            )
            teachers = (
                {} if rng is None else await reader.teacher_ids(ctx, subject_ids, *rng)
            )
            upcoming = (
                await reader.next_lessons(ctx, subject_ids, self._clock.now())
                if current
                else {}
            )
            view = await build_context(
                reader,
                self._identity,
                locale=locale,
                subject_ids=subject_ids,
                user_ids={t for ids in teachers.values() for t in ids},
                lessons=upcoming.values(),
            )
        cards = [
            _card(view, sid, rows.get(sid), counts, teachers, upcoming)
            for sid in subject_ids
        ]
        return sorted(cards, key=lambda c: str(c["subject"]["name"]).casefold())


def _card(
    view: ViewContext,
    subject_id: UUID,
    row: ResultRow | None,
    counts: dict[UUID, AttendanceCount],
    teachers: dict[UUID, list[UUID]],
    upcoming: dict[UUID, LessonRow],
) -> dict[str, Any]:
    people = (view.person(t) for t in teachers.get(subject_id, []))
    count = counts.get(subject_id)
    lesson = upcoming.get(subject_id)
    return {
        "subject": view.subject_ref(subject_id),
        "teachers": [p for p in people if p is not None],
        "semester_mark": None if row is None else num(row.value),
        "emis_rating": None if row is None else row.emis_rating,
        "absences": 0 if count is None else count.absences,
        "lates": 0 if count is None else count.lates,
        "next_lesson": None if lesson is None else view.lesson_item(lesson),
    }
