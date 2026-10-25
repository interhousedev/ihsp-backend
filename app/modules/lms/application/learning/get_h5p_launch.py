"""Use case: the signed base URL of an H5P block of a live step."""

from uuid import UUID

from app.modules.lms.application.h5p_links import H5PLinks
from app.modules.lms.application.learning.revision_loading import load_rendered
from app.modules.lms.application.learning.step_context import (
    load_live_step,
    staff_access,
)
from app.modules.lms.application.learning.types import UowFactory
from app.modules.lms.application.learning.views import H5PLaunchView
from app.modules.lms.domain.learning.errors import (
    CourseNotFoundError,
    H5PNotFoundError,
    NotEnrolledError,
)
from app.modules.lms.domain.learning.live import RenderCache
from app.shared.actor import Actor


class GetH5PLaunch:
    """Check enrollment (or staff), then sign the package's base URL."""

    def __init__(
        self, uow_factory: UowFactory, cache: RenderCache, links: H5PLinks
    ) -> None:
        """Store collaborators."""
        self.uow_factory = uow_factory
        self.cache = cache
        self.links = links

    async def execute(
        self, actor: Actor, course_id: UUID, step_id: UUID, block_id: str
    ) -> H5PLaunchView:
        """Return where the player loads the package from."""
        async with self.uow_factory() as uow:
            context = await load_live_step(uow, step_id)
            if context.course.id != course_id:
                raise CourseNotFoundError(params={"course_id": str(course_id)})
            enrolled = await uow.enrollments.get(course_id, actor.user_id)
            if (
                enrolled is None
                and not (await staff_access(uow, actor, course_id)).is_staff
            ):
                raise NotEnrolledError(params={"course_id": str(course_id)})
            rendered = await load_rendered(
                uow, self.cache, context.live_step.revision_id
            )
        package_id = next(
            (
                block.get("package_id")
                for block in rendered.blocks
                if block["id"] == block_id and block["type"] == "h5p"
            ),
            None,
        )
        if not package_id:
            raise H5PNotFoundError(params={"block_id": block_id})
        launch = self.links.launch(course_id, UUID(package_id))
        return H5PLaunchView(base_url=launch.base_url, expires_in=launch.expires_in)
