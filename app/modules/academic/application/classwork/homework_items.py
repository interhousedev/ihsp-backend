"""Builds ``HomeworkItem`` JSON from lessons and the student's to-do rows."""

from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

from app.modules.academic.application.classwork.lesson_items import subject_ref
from app.modules.academic.application.classwork.people import PeopleDirectory, Person
from app.modules.academic.domain.classwork.homework_rules import (
    days_overdue,
    is_updated,
)
from app.modules.academic.domain.classwork.records import HomeworkRecord
from app.modules.academic.domain.classwork.submission_rules import submission_status
from app.shared.clock import Clock, local_today


class HomeworkItemBuilder:
    """Resolves teachers and builds the to-do items."""

    def __init__(self, people: PeopleDirectory, clock: Clock) -> None:
        """Store the people directory and the clock that tells what is overdue."""
        self.people = people
        self.clock = clock

    async def build_many(
        self,
        records: Sequence[HomeworkRecord],
        locale: str,
        teachers: Mapping[UUID, Person] | None = None,
    ) -> list[dict[str, Any]]:
        """Build one item per record, in order.

        `teachers` are the already resolved people; without them one identity
        lookup resolves the teachers.
        """
        today = local_today(self.clock)
        if teachers is None:
            teachers = await self.people.people(
                record.lesson.teacher_id
                for record in records
                if record.lesson.teacher_id is not None
            )
        items = []
        for record in records:
            lesson, todo, submission = record.lesson, record.todo, record.submission
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
                    "submission": (
                        None
                        if submission is None
                        else {
                            "status": submission_status(
                                submission.submitted_at, lesson.homework_due_date
                            ),
                            "file_count": len(submission.file_ids),
                            "submitted_at": submission.submitted_at.isoformat(),
                        }
                    ),
                }
            )
        return items
