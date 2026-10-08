"""Use case: open the draft working copy of a course (LMS-6, LMS-7)."""

from uuid import UUID

from app.modules.lms.application.authoring.access import access_to, load_course
from app.modules.lms.application.authoring.presenter import Presenter
from app.modules.lms.application.authoring.uow_factory import UowFactory
from app.modules.lms.application.authoring.views import CourseDraftView
from app.modules.lms.domain.authoring.permissions import EDIT, VIEW_DRAFTS
from app.shared.actor import Actor


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
            return await self.presenter.course_draft(uow, course, access)
