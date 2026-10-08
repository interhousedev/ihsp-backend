"""Use case: the state of the end-of-lesson prompt for the teacher (BOT-16)."""

from collections.abc import Callable
from typing import Any
from uuid import UUID

from app.modules.academic.application.classwork.lookup import require_lesson
from app.modules.academic.application.classwork.people import PeopleDirectory
from app.modules.academic.application.classwork.ports.draft_store import (
    AttendanceDraftStore,
)
from app.modules.academic.application.classwork.ports.unit_of_work import (
    AttendanceUnitOfWork,
)
from app.modules.academic.application.classwork.prompt_state_builder import (
    PromptStateBuilder,
    ensure_prompt_teacher,
)


class GetPromptState:
    """Return the checklist with the toggles of the server-side draft."""

    def __init__(
        self,
        uow_factory: Callable[[], AttendanceUnitOfWork],
        people: PeopleDirectory,
        drafts: AttendanceDraftStore,
        builder: PromptStateBuilder,
    ) -> None:
        """Initialize the use case."""
        self.uow_factory = uow_factory
        self.people = people
        self.drafts = drafts
        self.builder = builder

    async def execute(self, lesson_id: UUID, teacher_id: UUID) -> dict[str, Any]:
        """Return the prompt state; raise LessonReassignedError for another teacher."""
        locale = await self.people.locale(teacher_id)
        async with self.uow_factory() as uow:
            lesson = await require_lesson(uow, lesson_id)
            ensure_prompt_teacher(lesson, teacher_id)
            roster = await self.builder.roster_for(uow, lesson)
        draft = await self.drafts.load(lesson_id)
        return self.builder.build(lesson, roster, locale, draft)
