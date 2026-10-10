"""One subject: averages, lessons, marks and materials (WEB-8)."""

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
from app.modules.academic.domain.marks.attendance import attendance_state
from app.modules.academic.domain.marks.errors import (
    StudentNotFoundError,
    SubjectNotFoundError,
)
from app.modules.academic.domain.marks.read_models import (
    AttendanceCount,
    LessonRow,
    MarkRow,
    ResultRow,
)
from app.modules.academic.domain.marks.semesters import resolve_semester
from app.shared.actor import Actor
from app.shared.clock import Clock, local_today
from app.shared.contracts.identity import IdentityDirectory
from app.shared.contracts.links import LinksApi, ResourceRef


class GetSubjectDetail:
    """Builds `SubjectDetail` for one subject of the student."""

    def __init__(
        self,
        *,
        uow_factory: MarksUowFactory,
        identity: IdentityDirectory,
        links: LinksApi,
        clock: Clock,
    ) -> None:
        """Store collaborators."""
        self._uow_factory = uow_factory
        self._identity = identity
        self._links = links
        self._clock = clock

    async def execute(
        self, actor: Actor, subject_id: UUID, semester: int | None
    ) -> dict[str, Any]:
        """Return `SubjectDetail`; raises SubjectNotFoundError for a foreign subject."""
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
            row = next(
                (
                    r
                    for r in results
                    if r.semester == sem and r.subject_id == subject_id
                ),
                None,
            )
            rng = await semester_range(reader, ctx, sem, local_today(self._clock))
            lessons = (
                []
                if rng is None
                else await reader.lessons(
                    ctx, subject_id=subject_id, start=rng[0], end=rng[1]
                )
            )
            marks = await reader.marks(
                actor.user_id, semester=sem, subject_id=subject_id
            )
            counts = (
                {}
                if rng is None
                else await reader.attendance_counts(actor.user_id, *rng)
            )
            known = (
                subject_id in ctx.curriculum_subject_ids
                or row is not None
                or bool(marks)
                or bool(lessons)
            )
            resources = await self._links.resources_for_lessons(
                [lesson.id for lesson in lessons]
            )
            view = await build_context(
                reader,
                self._identity,
                locale=locale,
                subject_ids=[subject_id],
                user_ids={r.author_id for rs in resources.values() for r in rs},
                lessons=lessons,
                with_photos=True,
            )
        if not known or subject_id not in view.subjects:
            raise SubjectNotFoundError(params={"subject_id": str(subject_id)})
        return _detail(
            view,
            actor.user_id,
            subject_id,
            sem,
            row,
            lessons,
            marks,
            resources,
            counts.get(subject_id),
        )


def _detail(
    view: ViewContext,
    student_id: UUID,
    subject_id: UUID,
    semester: int,
    row: ResultRow | None,
    lessons: Sequence[LessonRow],
    marks: Sequence[MarkRow],
    resources: dict[UUID, list[ResourceRef]],
    count: AttendanceCount | None,
) -> dict[str, Any]:
    by_lesson: dict[UUID, list[dict[str, Any]]] = {}
    for mark in marks:
        if mark.lesson_id is not None:
            by_lesson.setdefault(mark.lesson_id, []).append(view.mark_item(mark))
    teacher_ids = list(
        dict.fromkeys(lesson.teacher_id for lesson in lessons if lesson.teacher_id)
    )
    people = (view.person(t, photo=True) for t in teacher_ids)
    teachers = [p for p in people if p is not None]
    return {
        "subject": view.subject_ref(subject_id),
        "semester": semester,
        "teachers": teachers,
        "averages": {
            "lesson": None if row is None else num(row.lesson_avg),
            "midterm": None if row is None else num(row.midterm_avg),
            "final": None if row is None else num(row.final_avg),
        },
        "semester_mark": None if row is None else num(row.value),
        "emis_rating": None if row is None else row.emis_rating,
        "absence_rate": _rate(count),
        "lessons": [_lesson(view, student_id, lesson, by_lesson) for lesson in lessons],
        "marks": [view.mark_item(m) for m in marks],
        "materials": _materials(view, lessons, resources),
    }


def _rate(count: AttendanceCount | None) -> float | None:
    if count is None or count.with_attendance == 0:
        return None
    return round(count.absences / count.with_attendance, 4)


def _lesson(
    view: ViewContext,
    student_id: UUID,
    lesson: LessonRow,
    marks: dict[UUID, list[dict[str, Any]]],
) -> dict[str, Any]:
    item = view.lesson_item(lesson)
    item["marks"] = marks.get(lesson.id, [])
    item["attendance"] = attendance_state(
        student_id,
        lesson.attendance_roster,
        lesson.attendance_absent,
        lesson.attendance_excused,
        lesson.attendance_late,
    )
    item["homework_text"] = lesson.homework_text
    return item


def _materials(
    view: ViewContext,
    lessons: Sequence[LessonRow],
    resources: dict[UUID, list[ResourceRef]],
) -> list[dict[str, Any]]:
    items = []
    for lesson in lessons:
        for ref in resources.get(lesson.id, []):
            if not ref.hidden:
                items.append(_resource(view, ref))
    return items


def _resource(view: ViewContext, ref: ResourceRef) -> dict[str, Any]:
    author = view.person(ref.author_id) or {
        "id": ref.author_id,
        "first_name": ref.author_first_name,
        "last_name": "",
    }
    return {
        "link_id": ref.link_id,
        "lesson_id": ref.lesson_id,
        "role": ref.role,
        "kind": ref.kind,
        "short_url": ref.short_url,
        "title": ref.title,
        "author": author,
        "hidden": ref.hidden,
        "source": ref.source,
        "file": None,
        "created_at": None,
    }
