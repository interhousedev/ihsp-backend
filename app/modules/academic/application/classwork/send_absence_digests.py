"""Use case: tell each curator which of their students were absent today (WO-4)."""

import datetime as dt
from collections import defaultdict
from collections.abc import Callable
from typing import Any
from uuid import UUID

from app.modules.academic.application.classwork.people import PeopleDirectory
from app.modules.academic.application.classwork.ports.unit_of_work import ViewUnitOfWork
from app.modules.academic.application.classwork.work_off_items import names_of
from app.modules.academic.domain.classwork.lesson import Lesson
from app.modules.academic.domain.classwork.records import StudentRecord
from app.shared.clock import Clock, local_today
from app.shared.notifications import NotificationDraft, NotificationType

AFTER_LESSONS = dt.timedelta(minutes=30)
SCHOOL_WEEKDAYS = 5  # Monday is 0; Saturday (5) and Sunday (6) are off


class SendAbsenceDigests:
    """Queue one ``curator_absences`` notice per curator and group after lessons end."""

    def __init__(
        self,
        uow_factory: Callable[[], ViewUnitOfWork],
        clock: Clock,
        people: PeopleDirectory,
    ) -> None:
        """Initialize the use case."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.people = people

    async def execute(self) -> dict[str, int]:
        """Queue today's digests; ``{"skipped": 1}``, ``{"waiting": 1}`` or counts.

        Repeated runs are safe: the dedupe key holds curator, group and date.
        """
        today = local_today(self.clock)
        if today.weekday() >= SCHOOL_WEEKDAYS:
            return {"skipped": 1}
        async with self.uow_factory() as uow:
            last_end = await uow.digest.last_lesson_end(today)
            if last_end is None:
                return {"skipped": 1}
            if self.clock.now() < last_end + AFTER_LESSONS:
                return {"waiting": 1}
            lessons = await uow.digest.lessons_with_absences(today)
            students = await self._students(uow, lessons)
            curators = await uow.digest.group_curators(
                list({s.group_id for s in students.values()})
            )
            tasks = {
                (w.lesson_id, w.student_id): w.text
                for w in await uow.work_offs.for_lessons([x.id for x in lessons])
            }
            drafts = await self._drafts(today, lessons, students, curators, tasks)
            uow.notify(*drafts)
            await uow.commit()
        return {"queued": len(drafts)}

    @staticmethod
    async def _students(
        uow: ViewUnitOfWork, lessons: list[Lesson]
    ) -> dict[UUID, StudentRecord]:
        ids = list({s for lesson in lessons for s in lesson.attendance_absent or ()})
        return {s.user_id: s for s in await uow.students.by_ids(ids)}

    async def _drafts(
        self,
        day: dt.date,
        lessons: list[Lesson],
        students: dict[UUID, StudentRecord],
        curators: dict[UUID, UUID | None],
        tasks: dict[tuple[UUID, UUID], str],
    ) -> list[NotificationDraft]:
        grouped: dict[tuple[UUID, UUID], list[tuple[Lesson, UUID]]] = defaultdict(list)
        for lesson in lessons:
            for student_id in lesson.attendance_absent or ():
                record = students.get(student_id)
                curator = None if record is None else curators.get(record.group_id)
                if record is not None and curator is not None:
                    grouped[(curator, record.group_id)].append((lesson, student_id))
        names = await names_of(
            self.people,
            [*(s for pairs in grouped.values() for _, s in pairs)]
            + [lesson.teacher_id for lesson in lessons],
        )
        drafts = []
        for (curator, group_id), pairs in grouped.items():
            locale = await self.people.locale(curator)
            items = _items(pairs, names, tasks, locale)
            group_name = students[pairs[0][1]].group_name
            payload: dict[str, Any] = {
                "date": day.isoformat(),
                "group_id": str(group_id),
                "group_name": group_name,
                "items": items,
            }
            key = f"curator_absences:{curator}:{group_id}:{day.isoformat()}"
            drafts.append(
                NotificationDraft(
                    user_id=curator,
                    type=NotificationType.CURATOR_ABSENCES,
                    payload=payload,
                    dedupe_key=key,
                )
            )
        return drafts


def _items(
    pairs: list[tuple[Lesson, UUID]],
    names: dict[UUID, str],
    tasks: dict[tuple[UUID, UUID], str],
    locale: str,
) -> list[dict[str, Any]]:
    items = [
        {
            "student_id": str(student_id),
            "student_name": names.get(student_id, "?"),
            "lesson_id": str(lesson.id),
            "period": lesson.period,
            "subject_name": lesson.subject_name(locale),
            "teacher_name": (
                "" if lesson.teacher_id is None else names.get(lesson.teacher_id, "")
            ),
            "excused": str(student_id) in lesson.excused_ids(),
            "work_off_text": tasks.get((lesson.id, student_id)),
        }
        for lesson, student_id in pairs
    ]
    items.sort(key=lambda i: (str(i["student_name"]).casefold(), i["period"]))
    return items
