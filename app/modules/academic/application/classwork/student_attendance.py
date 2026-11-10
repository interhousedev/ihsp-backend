"""Use case: the student's own attendance page (WEB-17, UF-WEB-12)."""

import datetime as dt
from collections.abc import Callable
from typing import Any
from uuid import UUID

from app.modules.academic.application.classwork.lesson_items import LessonItemBuilder
from app.modules.academic.application.classwork.people import PeopleDirectory
from app.modules.academic.application.classwork.ports.excuse_coverage import (
    ExcuseCoverage,
)
from app.modules.academic.application.classwork.ports.unit_of_work import (
    ViewUnitOfWork,
)
from app.modules.academic.application.classwork.student_context import (
    keys_of,
    require_student,
)
from app.modules.academic.domain.classwork.excuse_ref import ExcuseRef
from app.modules.academic.domain.classwork.names import localized
from app.modules.academic.domain.classwork.reports import rate
from app.shared.actor import Actor
from app.shared.clock import Clock, local_today


class StudentAttendance:
    """Absences per subject and per day and the list of missed lessons."""

    def __init__(
        self,
        uow_factory: Callable[[], ViewUnitOfWork],
        clock: Clock,
        people: PeopleDirectory,
        lesson_items: LessonItemBuilder,
        excuse_coverage: ExcuseCoverage,
    ) -> None:
        """Initialize the use case."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.people = people
        self.lesson_items = lesson_items
        self.excuse_coverage = excuse_coverage

    async def execute(
        self, actor: Actor, start: dt.date | None, end: dt.date | None
    ) -> dict[str, Any]:
        """Return the ``StudentAttendance`` JSON; the default range is the term."""
        now, today = self.clock.now(), local_today(self.clock)
        locale = await self.people.locale(actor.user_id)
        async with self.uow_factory() as uow:
            student = await require_student(uow, actor.user_id)
            if start is None or end is None:
                term = await uow.results.current_term(today)
                start = start or (term.starts_on if term else today)
                end = end or (term.ends_on if term else today)
            data = await uow.reports.student_attendance(
                student.user_id, keys_of(student), start, end, now
            )
        lessons = data.missed
        missed = await self.lesson_items.build_many(lessons, locale)
        excuses = (await self.excuse_coverage.effective(lessons)) if lessons else {}
        excused_by_subject: dict[UUID, int] = {}
        for lesson in lessons:
            if student.user_id in excuses.get(lesson.id, {}):
                excused_by_subject[lesson.subject_id] = (
                    excused_by_subject.get(lesson.subject_id, 0) + 1
                )
        summary = []
        for stat in data.subjects:
            name = localized(stat.names, locale)
            summary.append(
                {
                    "subject": {
                        "id": str(stat.subject_id),
                        "name": name,
                        "short_name": stat.short or name,
                    },
                    "absences": stat.absences,
                    "excused": excused_by_subject.get(stat.subject_id, 0),
                    "lessons": stat.lessons,
                    "rate": rate(stat.absences, stat.lessons),
                }
            )
        return {
            "from": start.isoformat(),
            "to": end.isoformat(),
            "summary": sorted(summary, key=lambda row: row["subject"]["name"]),
            "days": [
                {"date": day.isoformat(), "absences": count} for day, count in data.days
            ],
            "missed": [
                _missed(item, excuses.get(lesson.id, {}).get(student.user_id))
                for item, lesson in zip(missed, lessons, strict=True)
            ],
            "not_taken": data.not_taken,
        }


def _missed(item: dict[str, Any], excuse: ExcuseRef | None) -> dict[str, Any]:
    return {
        "lesson": item,
        "excused": excuse is not None,
        "excuse": None if excuse is None else excuse.as_dict(),
    }
