"""Use case: open the draft working copy of a course (LMS-6, LMS-7)."""

from uuid import UUID

from app.modules.lms.application.authoring.access import access_to, load_course
from app.modules.lms.application.authoring.presenter import Presenter
from app.modules.lms.application.authoring.uow_factory import UowFactory
from app.modules.lms.application.authoring.views import CourseDraftView
from app.modules.lms.domain.authoring.permissions import EDIT, VIEW_DRAFTS, CourseAccess
from app.shared.actor import SYSTEM_ACTOR, Actor


class GetCourseDraft:
    """Return the draft outline with badges and the pending count."""

    def __init__(self, uow_factory: UowFactory, presenter: Presenter) -> None:
        """Store collaborators."""
        self.uow_factory = uow_factory
        self.presenter = presenter

    async def execute(self, actor: Actor, course_id: UUID) -> CourseDraftView:
        """Return `CourseDraft` for staff with `edit` or `view_drafts`."""
        async with self.uow_factory() as uow:
            course = await load_course(uow, course_id)
            access = await access_to(uow, actor, course_id)
            access.require(EDIT, VIEW_DRAFTS)
            access.require_read_scope()
            return await self.presenter.course_draft(uow, course, access)

    async def unchecked(self, course_id: UUID) -> CourseDraftView | None:
        """Return `CourseDraft` without any access check; None for an unknown course.

        For callers that have just checked the access themselves, such as the course
        workspace: the view is built as for an LMS admin.
        """
        async with self.uow_factory() as uow:
            course = await uow.courses.get(course_id)
            if course is None:
                return None
            access = CourseAccess(actor=SYSTEM_ACTOR, staff=None)
            return await self.presenter.course_draft(uow, course, access)
