"""Use case: list the staff of a course (LMS-4, UF-LMS-07)."""

from uuid import UUID

from app.modules.lms.application.authoring.access import access_to, load_course
from app.modules.lms.application.authoring.presenter import Presenter
from app.modules.lms.application.authoring.uow_factory import UowFactory
from app.modules.lms.application.authoring.views import CourseStaffItemView
from app.shared.actor import Actor


class ListCourseStaff:
    """Return every staff member, including those hidden from the course page."""

    def __init__(self, uow_factory: UowFactory, presenter: Presenter) -> None:
        """Store collaborators."""
        self.uow_factory = uow_factory
        self.presenter = presenter

    async def execute(self, actor: Actor, course_id: UUID) -> list[CourseStaffItemView]:
        """Return the staff ordered by position (course staff only)."""
        async with self.uow_factory() as uow:
            await load_course(uow, course_id)
            access = await access_to(uow, actor, course_id)
            access.require_staff()
            members = await uow.staff.list_for_course(course_id)
        return await self.presenter.staff_items(members)
