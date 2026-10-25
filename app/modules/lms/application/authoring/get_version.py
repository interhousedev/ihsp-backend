"""Use case: open a published version read-only (LMS-11, UF-LMS-11)."""

from uuid import UUID

from app.modules.lms.application.authoring.access import access_to, load_course
from app.modules.lms.application.authoring.presenter import Presenter
from app.modules.lms.application.authoring.uow_factory import UowFactory
from app.modules.lms.application.authoring.views import (
    VersionDetailView,
    VersionMetaView,
)
from app.modules.lms.domain.authoring.errors import VersionNotFoundError
from app.modules.lms.domain.authoring.manifest import parse_manifest
from app.shared.actor import Actor


class GetVersion:
    """Return one version with its title, description and outline."""

    def __init__(self, uow_factory: UowFactory, presenter: Presenter) -> None:
        """Store collaborators."""
        self.uow_factory = uow_factory
        self.presenter = presenter

    async def execute(
        self, actor: Actor, course_id: UUID, number: int
    ) -> VersionDetailView:
        """Return `VersionView` for course staff."""
        async with self.uow_factory() as uow:
            await load_course(uow, course_id)
            access = await access_to(uow, actor, course_id)
            access.require_staff()
            version = await uow.versions.get_by_number(course_id, number)
            if version is None:
                raise VersionNotFoundError(params={"number": number})
        item = (await self.presenter.version_items([version]))[0]
        return VersionDetailView(
            **item.model_dump(),
            meta=VersionMetaView(
                title=version.meta.get("title", ""),
                description=version.meta.get("description", ""),
            ),
            outline=self.presenter.manifest_outline(parse_manifest(version.outline)),
        )
