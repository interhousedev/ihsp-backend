"""Use case: who gets a course broadcast (the students enrolled in the course)."""

from dataclasses import dataclass
from uuid import UUID

from app.modules.lms.application.learning.step_context import (
    load_course,
    staff_access,
)
from app.modules.lms.application.learning.types import UowFactory
from app.modules.lms.domain.learning.errors import CoursePermissionError
from app.shared.actor import Actor

PUBLISH = "publish"
MANAGE_STAFF = "manage_staff"


@dataclass(frozen=True, slots=True)
class BroadcastAudience:
    """The course a broadcast goes to and the students enrolled in it."""

    course_id: UUID
    slug: str
    title: str
    user_ids: tuple[UUID, ...]
    can_manage: bool = False


class ListBroadcastAudience:
    """Check that the actor runs the course and list the enrolled students."""

    def __init__(self, uow_factory: UowFactory) -> None:
        """Store the unit of work factory."""
        self.uow_factory = uow_factory

    async def execute(self, actor: Actor, course_id: UUID) -> BroadcastAudience:
        """Return the audience; needs `publish` or `manage_staff` in the course."""
        async with self.uow_factory() as uow:
            course = await load_course(uow, course_id)
            access = await staff_access(uow, actor, course_id)
            if not (access.can(PUBLISH) or access.can(MANAGE_STAFF)):
                raise CoursePermissionError(params={"permission": PUBLISH})
            enrollments = await uow.enrollments.list_for_course(course_id)
        return BroadcastAudience(
            course_id=course.id,
            slug=course.slug,
            title=course.title,
            user_ids=tuple(dict.fromkeys(e.user_id for e in enrollments)),
            can_manage=access.can(MANAGE_STAFF),
        )
