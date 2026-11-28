"""Use cases: a teacher's homework defaults and a lesson's homework switches."""

from collections.abc import Callable
from typing import Any
from uuid import UUID

from app.modules.academic.application.classwork.lookup import require_lesson
from app.modules.academic.application.classwork.ports.unit_of_work import (
    LessonUnitOfWork,
)
from app.modules.academic.application.classwork.staff_lesson import StaffLesson
from app.modules.academic.domain.classwork.attendance_rules import ensure_lesson_staff
from app.modules.academic.domain.classwork.errors import (
    HomeworkCancelledLessonError,
    HomeworkNotFoundError,
)
from app.modules.academic.domain.classwork.records import TeacherHomeworkSettings
from app.shared.actor import Actor
from app.shared.clock import Clock

UowFactory = Callable[[], LessonUnitOfWork]


def settings_json(settings: TeacherHomeworkSettings) -> dict[str, Any]:
    """``HomeworkSettings``: the caller's own defaults."""
    return {
        "accept_by_default": settings.accept_by_default,
        "notify_on_submission": settings.notify_on_submission,
    }


class GetHomeworkSettings:
    """The caller's homework defaults (defaults when never saved)."""

    def __init__(self, uow_factory: UowFactory) -> None:
        """Initialize the use case."""
        self.uow_factory = uow_factory

    async def execute(self, actor: Actor) -> dict[str, Any]:
        """Return ``HomeworkSettings``."""
        async with self.uow_factory() as uow:
            return settings_json(await uow.homework_settings.get(actor.user_id))


class SaveHomeworkSettings:
    """Change the caller's homework defaults; None keeps a field."""

    def __init__(self, uow_factory: UowFactory, clock: Clock) -> None:
        """Initialize the use case."""
        self.uow_factory = uow_factory
        self.clock = clock

    async def execute(
        self,
        actor: Actor,
        *,
        accept_by_default: bool | None = None,
        notify_on_submission: bool | None = None,
    ) -> dict[str, Any]:
        """Save and return ``HomeworkSettings``."""
        async with self.uow_factory() as uow:
            saved = await uow.homework_settings.save(
                actor.user_id,
                accept_by_default=accept_by_default,
                notify_on_submission=notify_on_submission,
                now=self.clock.now(),
            )
            await uow.commit()
        return settings_json(saved)


class SetLessonHomeworkSwitches:
    """Open or close submissions and override the teacher's notification setting."""

    def __init__(
        self, uow_factory: UowFactory, clock: Clock, staff_lesson: StaffLesson
    ) -> None:
        """Initialize the use case."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.staff_lesson = staff_lesson

    async def execute(
        self,
        lesson_id: UUID,
        actor: Actor,
        *,
        accept_submissions: bool | None = None,
        notify: bool | None = None,
        change_notify: bool = False,
    ) -> dict[str, Any]:
        """Save the switches and return the ``StaffLesson`` JSON.

        ``accept_submissions`` None keeps the switch; ``change_notify`` with
        ``notify`` None makes the lesson follow the teacher's setting again.

        Raises:
            NotLessonTeacherError: The actor neither teaches the lesson nor is admin.
            HomeworkCancelledLessonError: The lesson is cancelled.
            HomeworkNotFoundError: The lesson has no homework.
        """
        async with self.uow_factory() as uow:
            lesson = await require_lesson(uow, lesson_id)
            ensure_lesson_staff(lesson, actor)
            if not lesson.scheduled:
                raise HomeworkCancelledLessonError(params={"lesson_id": str(lesson_id)})
            if not lesson.has_homework:
                raise HomeworkNotFoundError(params={"lesson_id": str(lesson_id)})
            await uow.lessons.set_homework_switches(
                lesson_id,
                accept_submissions=accept_submissions,
                notify=notify,
                change_notify=change_notify,
                at=self.clock.now(),
            )
            await uow.commit()
        return await self.staff_lesson.execute(lesson_id, actor)
