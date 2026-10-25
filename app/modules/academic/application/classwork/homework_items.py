"""Builds ``HomeworkItem`` JSON from lessons and the student's to-do rows."""

from collections.abc import Sequence
from typing import Any

from app.modules.academic.application.classwork.lesson_items import subject_ref
from app.modules.academic.application.classwork.people import PeopleDirectory
from app.modules.academic.domain.classwork.homework_rules import (
    days_overdue,
    is_updated,
)
from app.modules.academic.domain.classwork.records import HomeworkRecord
from app.shared.clock import Clock, local_today


class HomeworkItemBuilder:
    """Resolves teachers and builds the to-do items."""

    def __init__(self, people: PeopleDirectory, clock: Clock) -> None:
        """Store the people directory and the clock that tells what is overdue."""
        self.people = people
        self.clock = clock

    async def build_many(
        self, records: Sequence[HomeworkRecord], locale: str
    ) -> list[dict[str, Any]]:
        """Build one item per record, in order."""
        today = local_today(self.clock)
        teachers = await self.people.people(
            record.lesson.teacher_id
            for record in records
            if record.lesson.teacher_id is not None
        )
        items = []
        for record in records:
            lesson, todo = record.lesson, record.todo
            teacher_id = lesson.teacher_id
            teacher = teachers.get(teacher_id) if teacher_id else None
            items.append(
                {
                    "lesson_id": str(lesson.id),
                    "subject": subject_ref(lesson, locale),
                    "teacher": None if teacher is None else teacher.to_json(),
                    "text": lesson.homework_text or "",
                    "due_date": (
                        lesson.homework_due_date.isoformat()
                        if lesson.homework_due_date
                        else None
                    ),
                    "given_on": lesson.date.isoformat(),
                    "days_overdue": days_overdue(
                        todo.done_at if todo else None,
                        lesson.homework_due_date,
                        today,
                    ),
                    "updated": is_updated(
                        lesson.homework_updated_at, todo.updated_at if todo else None
                    ),
                    "done_at": (
                        todo.done_at.isoformat() if todo and todo.done_at else None
                    ),
                    "note": todo.note if todo else None,
                }
            )
        return items
