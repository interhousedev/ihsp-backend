"""Resolving a step of the live version together with its course and access."""

from dataclasses import dataclass
from uuid import UUID

from app.modules.lms.domain.learning.access import StaffAccess
from app.modules.lms.domain.learning.entities import (
    LearningCourse,
    LearningStep,
    LiveVersion,
)
from app.modules.lms.domain.learning.errors import (
    CourseNotFoundError,
    StepNotFoundError,
)
from app.modules.lms.domain.learning.live import LiveStep
from app.modules.lms.ports.learning.unit_of_work import LearningUnitOfWork
from app.shared.actor import Actor


@dataclass(frozen=True, slots=True)
class StepContext:
    """A step as the live version of its course pins it."""

    step: LearningStep
    course: LearningCourse
    version: LiveVersion
    live_step: LiveStep


async def load_live_step(uow: LearningUnitOfWork, step_id: UUID) -> StepContext:
    """Return the step with its live version, or raise StepNotFoundError.

    A step that is not in the live manifest (new, or removed from the outline)
    does not exist for learners.
    """
    step = await uow.steps.get(step_id)
    if step is None:
        raise StepNotFoundError(params={"step_id": str(step_id)})
    course = await uow.courses.get(step.course_id)
    version = (
        await uow.versions.get(course.live_version_id)
        if course is not None and course.live_version_id is not None
        else None
    )
    live_step = version.manifest.find(step_id) if version is not None else None
    if course is None or version is None or live_step is None:
        raise StepNotFoundError(params={"step_id": str(step_id)})
    return StepContext(step=step, course=course, version=version, live_step=live_step)


async def load_course(uow: LearningUnitOfWork, course_id: UUID) -> LearningCourse:
    """Return the course or raise CourseNotFoundError."""
    course = await uow.courses.get(course_id)
    if course is None:
        raise CourseNotFoundError(params={"course_id": str(course_id)})
    return course


async def staff_access(
    uow: LearningUnitOfWork, actor: Actor, course_id: UUID
) -> StaffAccess:
    """Return what the actor may do as staff in the course."""
    return StaffAccess(
        actor=actor, member=await uow.staff.get(course_id, actor.user_id)
    )
