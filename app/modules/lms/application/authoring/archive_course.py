"""Use case: delete a course the safe way, by archiving it (MCP `delete_course`)."""

from uuid import UUID

from app.modules.lms.application.authoring.access import (
    access_to,
    load_course_locked,
)
from app.modules.lms.application.authoring.uow_factory import UowFactory
from app.modules.lms.domain.authoring.enums import CourseStatus
from app.modules.lms.domain.authoring.permissions import MANAGE_STAFF
from app.shared.actor import Actor
from app.shared.lms_scopes import COURSES_DELETE


class ArchiveCourse:
    """Close a course to students; the content and the attempts stay in the database.

    Needs the course owner (or an LMS admin) and, for a connector, `lms.courses.delete`.
    """

    def __init__(self, uow_factory: UowFactory) -> None:
        """Store collaborators."""
        self.uow_factory = uow_factory

    async def execute(self, actor: Actor, course_id: UUID) -> CourseStatus:
        """Archive the course; archiving twice changes nothing."""
        async with self.uow_factory() as uow:
            course = await load_course_locked(uow, course_id)
            access = await access_to(uow, actor, course_id)
            access.require(MANAGE_STAFF)
            access.require_scope(COURSES_DELETE)
            if course.status is not CourseStatus.ARCHIVED:
                course.status = CourseStatus.ARCHIVED
                await uow.courses.save(course)
                await uow.commit()
            return course.status
