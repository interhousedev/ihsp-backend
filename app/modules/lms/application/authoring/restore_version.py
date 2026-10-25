"""Use case: copy an old version into the draft (LMS-11, UF-LMS-12)."""

from uuid import UUID

from app.modules.lms.application.authoring.access import (
    access_to,
    load_course_locked,
)
from app.modules.lms.application.authoring.presenter import Presenter
from app.modules.lms.application.authoring.uow_factory import UowFactory
from app.modules.lms.application.authoring.version_applier import (
    copy_version_into_draft,
)
from app.modules.lms.application.authoring.views import CourseDraftView
from app.modules.lms.domain.authoring.errors import VersionNotFoundError
from app.modules.lms.domain.authoring.permissions import EDIT
from app.shared.actor import Actor
from app.shared.clock import Clock
from app.shared.lms_scopes import COURSES_WRITE


class RestoreVersion:
    """Restore a version into the draft; publishing it later creates a new version."""

    def __init__(
        self, uow_factory: UowFactory, clock: Clock, presenter: Presenter
    ) -> None:
        """Store collaborators."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.presenter = presenter

    async def execute(
        self, actor: Actor, course_id: UUID, number: int
    ) -> CourseDraftView:
        """Copy meta, outline and step contents; history is never rewritten."""
        async with self.uow_factory() as uow:
            course = await load_course_locked(uow, course_id)
            access = await access_to(uow, actor, course_id)
            access.require(EDIT)
            access.require_scope(COURSES_WRITE)
            version = await uow.versions.get_by_number(course_id, number)
            if version is None:
                raise VersionNotFoundError(params={"number": number})
            await copy_version_into_draft(
                uow, course, version, actor_id=actor.user_id, now=self.clock.now()
            )
            await uow.commit()
            return await self.presenter.course_draft(uow, course, access)
