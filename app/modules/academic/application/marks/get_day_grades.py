"""Marks of one day placed on their lessons (WEB-14, ACA-14)."""

import datetime as dt
from typing import Any

from app.modules.academic.application.marks.ports.unit_of_work import MarksUowFactory
from app.modules.academic.application.marks.view_context import (
    build_context,
    caller_locale,
)
from app.modules.academic.domain.marks.errors import StudentNotFoundError
from app.shared.actor import Actor
from app.shared.contracts.identity import IdentityDirectory


class GetDayGrades:
    """Builds `DayGrades` for one date."""

    def __init__(
        self, *, uow_factory: MarksUowFactory, identity: IdentityDirectory
    ) -> None:
        """Store collaborators."""
        self._uow_factory = uow_factory
        self._identity = identity

    async def execute(self, actor: Actor, day: dt.date) -> dict[str, Any]:
        """Return the day's lessons with their marks and the marks without a lesson."""
        locale = await caller_locale(self._identity, actor.user_id)
        async with self._uow_factory() as uow:
            ctx = await uow.reader.student_context(actor.user_id)
            if ctx is None:
                raise StudentNotFoundError()
            lessons = await uow.reader.lessons(ctx, start=day, end=day)
            marks = await uow.reader.marks(actor.user_id, start=day, end=day)
            view = await build_context(
                uow.reader,
                self._identity,
                locale=locale,
                subject_ids={m.subject_id for m in marks},
                lessons=lessons,
            )
        listed = {lesson.id for lesson in lessons}
        return {
            "date": day,
            "lessons": [
                {
                    "lesson": view.lesson_item(lesson),
                    "marks": [
                        view.mark_item(m) for m in marks if m.lesson_id == lesson.id
                    ],
                }
                for lesson in lessons
            ],
            "unmatched": [
                view.mark_item(m) for m in marks if m.lesson_id not in listed
            ],
        }
