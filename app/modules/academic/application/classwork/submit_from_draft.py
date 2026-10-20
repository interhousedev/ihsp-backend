"""Use case: submit attendance from the bot, using the draft if there is one."""

from collections.abc import Callable, Mapping, Sequence
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
)
from app.modules.academic.application.classwork.submit_attendance import (
    Source,
    SubmitAttendance,
)
from app.modules.academic.domain.classwork.errors import (
    AttendanceConflictError,
    LessonReassignedError,
    NotLessonTeacherError,
)
from app.modules.academic.domain.classwork.work_off import (
    WorkOffChoice,
    WorkOffEntry,
    WorkOffMode,
)
from app.shared.actor import Actor


class SubmitFromDraft:
    """Save the draft's list against the version the draft started from."""

    def __init__(
        self,
        uow_factory: Callable[[], AttendanceUnitOfWork],
        people: PeopleDirectory,
        drafts: AttendanceDraftStore,
        submit: SubmitAttendance,
        builder: PromptStateBuilder,
    ) -> None:
        """Initialize the use case."""
        self.uow_factory = uow_factory
        self.people = people
        self.drafts = drafts
        self.submit = submit
        self.builder = builder

    async def execute(
        self,
        lesson_id: UUID,
        actor: Actor,
        *,
        absent: Sequence[UUID] | None,
        from_draft: bool,
        base_version: int,
        source: Source,
        work_off_mode: WorkOffMode = "per_student",
        work_offs: Sequence[WorkOffEntry | Mapping[str, Any]] = (),
        common_work_off: WorkOffChoice | Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Submit and return the prompt state; a stale draft is dropped on conflict.

        Raises:
            AttendanceConflictError: someone else changed the attendance.
            LessonReassignedError: the actor no longer teaches the lesson.
        """
        draft = await self.drafts.load(lesson_id) if from_draft else None
        absent_ids = list(draft.absent if draft else (absent or ()))
        version = draft.base_version if draft else base_version
        try:
            await self.submit.execute(
                lesson_id=lesson_id,
                actor=actor,
                absent=absent_ids,
                base_version=version,
                source=source,
                work_off_mode=work_off_mode,
                work_offs=work_offs,
                common_work_off=common_work_off,
            )
        except AttendanceConflictError:
            await self.drafts.delete(lesson_id)
            raise
        except NotLessonTeacherError as error:
            raise LessonReassignedError(params=error.params) from error
        await self.drafts.delete(lesson_id)
        locale = await self.people.locale(actor.user_id)
        async with self.uow_factory() as uow:
            lesson = await require_lesson(uow, lesson_id)
            roster = await self.builder.roster_for(uow, lesson)
        return self.builder.build(lesson, roster, locale, None)
