"""Use case: list the published versions of a course (LMS-11)."""

from uuid import UUID

from app.modules.lms.application.authoring.access import access_to, load_course
from app.modules.lms.application.authoring.presenter import Presenter
from app.modules.lms.application.authoring.uow_factory import UowFactory
from app.modules.lms.application.authoring.views import VersionItemView
from app.shared.actor import Actor


class ListVersions:
    """Return all versions, newest first."""

    def __init__(self, uow_factory: UowFactory, presenter: Presenter) -> None:
        """Store collaborators."""
        self.uow_factory = uow_factory
        self.presenter = presenter

    async def execute(self, actor: Actor, course_id: UUID) -> list[VersionItemView]:
        """Return `VersionItem`s for course staff."""
        async with self.uow_factory() as uow:
            await load_course(uow, course_id)
            access = await access_to(uow, actor, course_id)
            access.require_staff()
            versions = await uow.versions.list_for_course(course_id)
        return await self.presenter.version_items(versions)
