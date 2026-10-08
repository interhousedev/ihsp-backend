"""Use case: discard all pending changes of a course (LMS-10, UF-LMS-12)."""

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
from app.modules.lms.domain.authoring.errors import (
    NoLiveVersionError,
    VersionNotFoundError,
)
from app.modules.lms.domain.authoring.permissions import EDIT
from app.shared.actor import Actor
from app.shared.clock import Clock


class DiscardCourse:
    """Reset the whole draft (meta, outline, every step) to the live version."""

    def __init__(
        self, uow_factory: UowFactory, clock: Clock, presenter: Presenter
    ) -> None:
        """Store collaborators."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.presenter = presenter

    async def execute(self, actor: Actor, course_id: UUID) -> CourseDraftView:
        """Copy the live version into the draft; a never-published course has none."""
        async with self.uow_factory() as uow:
            course = await load_course_locked(uow, course_id)
            access = await access_to(uow, actor, course_id)
            access.require(EDIT)
            if course.live_version_id is None:
                raise NoLiveVersionError(params={"course_id": str(course_id)})
            version = await uow.versions.get(course.live_version_id)
            if version is None:
                raise VersionNotFoundError()
            await copy_version_into_draft(
                uow, course, version, actor_id=actor.user_id, now=self.clock.now()
            )
            await uow.commit()
            return await self.presenter.course_draft(uow, course, access)
