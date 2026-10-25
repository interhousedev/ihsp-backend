"""The lesson list of one subject around now (subject hub)."""

from typing import Any
from uuid import UUID

from app.modules.academic.application.marks.ports.unit_of_work import MarksUowFactory
from app.modules.academic.application.marks.semester_range import semester_range
from app.modules.academic.domain.marks.errors import (
    StudentNotFoundError,
    SubjectNotFoundError,
)
from app.modules.academic.domain.marks.semesters import resolve_semester
from app.modules.academic.domain.marks.subject_lessons import (
    PAST_PAGE,
    UPCOMING_DAYS,
    build_subject_lessons,
)
from app.shared.actor import Actor
from app.shared.clock import Clock, local_today
from app.shared.contracts.links import LinksApi


class ListSubjectLessons:
    """Builds `SubjectLessonList` for one subject of the student."""

    def __init__(
        self, *, uow_factory: MarksUowFactory, links: LinksApi, clock: Clock
    ) -> None:
        """Store collaborators."""
        self._uow_factory = uow_factory
        self._links = links
        self._clock = clock

    async def execute(
        self,
        actor: Actor,
        subject_id: UUID,
        *,
        semester: int | None = None,
        past_limit: int = PAST_PAGE,
        past_offset: int = 0,
        upcoming_days: int = UPCOMING_DAYS,
    ) -> dict[str, Any]:
        """Return the latest past lessons plus the upcoming ones."""
        now = self._clock.now()
        async with self._uow_factory() as uow:
            reader = uow.reader
            ctx = await reader.student_context(actor.user_id)
            if ctx is None:
                raise StudentNotFoundError()
            results = await reader.results(actor.user_id, None)
            sem = resolve_semester(
                semester, ctx.current_semester, {r.semester for r in results}
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
            if not lessons and subject_id not in ctx.curriculum_subject_ids:
                raise SubjectNotFoundError(params={"subject_id": str(subject_id)})
        resources = await self._links.resources_for_lessons([x.id for x in lessons])
        page = build_subject_lessons(
            lessons,
            student_id=actor.user_id,
            now=now,
            marks=marks,
            materials={
                lid: sum(1 for r in refs if not r.hidden)
                for lid, refs in resources.items()
            },
            past_limit=past_limit,
            past_offset=past_offset,
            upcoming_days=upcoming_days,
        )
        return {
            "items": [
                {
                    "lesson_id": v.lesson_id,
                    "date": v.date,
                    "starts_at": v.starts_at,
                    "kind": v.kind,
                    "topic": v.topic,
                    "marks": [{"type": m.type, "value": m.value} for m in v.marks],
                    "attendance": v.attendance,
                    "materials_count": v.materials_count,
                    "past": v.past,
                }
                for v in page.items
            ],
            "has_more_past": page.has_more_past,
        }
