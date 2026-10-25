"""Use case: the signed base URL of a draft's H5P package (editor and preview)."""

from uuid import UUID

from app.modules.lms.application.authoring.access import access_to, load_step
from app.modules.lms.application.authoring.uow_factory import UowFactory
from app.modules.lms.application.authoring.views import H5PLaunchView
from app.modules.lms.application.h5p_links import H5PLinks
from app.modules.lms.domain.authoring.errors import (
    H5PBlockNotFoundError,
    StepNotFoundError,
)
from app.modules.lms.domain.authoring.permissions import VIEW_DRAFTS
from app.modules.lms.domain.step_content import H5PBlock, StepContent
from app.shared.actor import Actor


class PreviewH5P:
    """Launch URL of a draft's H5P block; needs `view_drafts` like the preview."""

    def __init__(self, uow_factory: UowFactory, links: H5PLinks) -> None:
        """Store the unit of work factory and the link signer."""
        self.uow_factory = uow_factory
        self.links = links

    async def execute(
        self, actor: Actor, course_id: UUID, step_id: UUID, block_id: str
    ) -> H5PLaunchView:
        """Return the signed base URL of the block's package."""
        async with self.uow_factory() as uow:
            step = await load_step(uow, step_id)
            if step.course_id != course_id:
                raise StepNotFoundError(params={"step_id": str(step_id)})
            (await access_to(uow, actor, course_id)).require(VIEW_DRAFTS)
        content = StepContent.model_validate(step.draft)
        package_id = next(
            (
                block.package_id
                for block in content.blocks
                if isinstance(block, H5PBlock) and block.id == block_id
            ),
            "",
        )
        if not package_id:
            raise H5PBlockNotFoundError(params={"block_id": block_id})
        launch = self.links.launch(course_id, UUID(package_id))
        return H5PLaunchView(base_url=launch.base_url, expires_in=launch.expires_in)
