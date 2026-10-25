"""Loading courses and steps together with the actor's access."""

from uuid import UUID

from app.modules.lms.domain.authoring.entities import Course, CourseStep
from app.modules.lms.domain.authoring.errors import (
    CourseNotFoundError,
    StepNotFoundError,
)
from app.modules.lms.domain.authoring.permissions import CourseAccess
from app.modules.lms.ports.authoring.unit_of_work import AuthoringUnitOfWork
from app.shared.actor import Actor


async def load_course(uow: AuthoringUnitOfWork, course_id: UUID) -> Course:
    """Return the course or raise CourseNotFoundError."""
    course = await uow.courses.get(course_id)
    if course is None:
        raise CourseNotFoundError(params={"course_id": str(course_id)})
    return course


async def load_course_locked(uow: AuthoringUnitOfWork, course_id: UUID) -> Course:
    """Return the course with its row locked, or raise CourseNotFoundError."""
    course = await uow.courses.get_locked(course_id)
    if course is None:
        raise CourseNotFoundError(params={"course_id": str(course_id)})
    return course


async def load_step(uow: AuthoringUnitOfWork, step_id: UUID) -> CourseStep:
    """Return the step or raise StepNotFoundError."""
    step = await uow.steps.get(step_id)
    if step is None:
        raise StepNotFoundError(params={"step_id": str(step_id)})
    return step


async def access_to(
    uow: AuthoringUnitOfWork, actor: Actor, course_id: UUID
) -> CourseAccess:
    """Return what the actor may do in the course."""
    staff = await uow.staff.get(course_id, actor.user_id)
    return CourseAccess(actor=actor, staff=staff)
