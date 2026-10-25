"""Use case: the student's own attendance page (WEB-17, UF-WEB-12)."""

import datetime as dt
from collections.abc import Callable
from typing import Any

from app.modules.academic.application.classwork.lesson_items import LessonItemBuilder
from app.modules.academic.application.classwork.people import PeopleDirectory
from app.modules.academic.application.classwork.ports.unit_of_work import (
    ViewUnitOfWork,
)
from app.modules.academic.application.classwork.student_context import (
    keys_of,
    require_student,
)
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
    ) -> None:
        """Initialize the use case."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.people = people
        self.lesson_items = lesson_items

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
        missed = await self.lesson_items.build_many(
            [lesson for lesson, _ in data.missed], locale
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
                    "excused": stat.excused,
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
                {"lesson": item, "excused": excused}
                for item, (_, excused) in zip(missed, data.missed, strict=True)
            ],
            "not_taken": data.not_taken,
        }
