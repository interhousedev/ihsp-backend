"""Use case: list the pending changes of a course (LMS-7, LMS-9)."""

from uuid import UUID

from app.modules.lms.application.authoring.access import access_to, load_course
from app.modules.lms.application.authoring.pending_loader import load_pending
from app.modules.lms.application.authoring.presenter import Presenter
from app.modules.lms.application.authoring.uow_factory import UowFactory
from app.modules.lms.application.authoring.views import PendingChangesView
from app.modules.lms.domain.authoring.permissions import EDIT, PUBLISH
from app.shared.actor import Actor


class GetPendingChanges:
    """Compare draft hashes with the live version; no content diffing."""

    def __init__(self, uow_factory: UowFactory, presenter: Presenter) -> None:
        """Store collaborators."""
        self.uow_factory = uow_factory
        self.presenter = presenter

    async def execute(self, actor: Actor, course_id: UUID) -> PendingChangesView:
        """Return added, changed and removed steps and whether the outline changed."""
        async with self.uow_factory() as uow:
            course = await load_course(uow, course_id)
            access = await access_to(uow, actor, course_id)
            access.require(EDIT, PUBLISH)
            context = await load_pending(uow, course)
        return self.presenter.pending_changes(context.pending)
