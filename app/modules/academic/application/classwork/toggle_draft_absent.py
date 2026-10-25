"""Use case: toggle one student in the server-side attendance draft (BOT-16)."""

from collections.abc import Callable
from typing import Any
from uuid import UUID

from app.modules.academic.application.classwork.lookup import require_lesson
from app.modules.academic.application.classwork.people import PeopleDirectory
from app.modules.academic.application.classwork.ports.draft_store import (
    AttendanceDraft,
    AttendanceDraftStore,
)
from app.modules.academic.application.classwork.ports.unit_of_work import (
    AttendanceUnitOfWork,
)
from app.modules.academic.application.classwork.prompt_state_builder import (
    PromptStateBuilder,
    draft_ttl_seconds,
    ensure_prompt_teacher,
)
from app.shared.clock import Clock


class ToggleDraftAbsent:
    """Flip the student at a position; the draft survives bot restarts."""

    def __init__(
        self,
        uow_factory: Callable[[], AttendanceUnitOfWork],
        clock: Clock,
        people: PeopleDirectory,
        drafts: AttendanceDraftStore,
        builder: PromptStateBuilder,
    ) -> None:
        """Initialize the use case."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.people = people
        self.drafts = drafts
        self.builder = builder

    async def execute(
        self, lesson_id: UUID, teacher_id: UUID, position: int
    ) -> dict[str, Any]:
        """Toggle and return the prompt state; an expired prompt is not changed."""
        locale = await self.people.locale(teacher_id)
        async with self.uow_factory() as uow:
            lesson = await require_lesson(uow, lesson_id)
            ensure_prompt_teacher(lesson, teacher_id)
            roster = await self.builder.roster_for(uow, lesson)
        draft = await self.drafts.load(lesson_id)
        student = roster.student_at(position)
        if student is not None and not self.builder.expired(lesson):
            if draft is None:
                draft = AttendanceDraft(
                    base_version=lesson.attendance_version,
                    absent=list(lesson.attendance_absent or ()),
                )
            if student.user_id in draft.absent:
                draft.absent.remove(student.user_id)
            else:
                draft.absent.append(student.user_id)
            ttl = draft_ttl_seconds(lesson, self.clock.now())
            await self.drafts.save(lesson_id, draft, ttl)
        return self.builder.build(lesson, roster, locale, draft)
