"""Use case: the signed URL of a draft's HTML widget (editor and preview)."""

from uuid import UUID

from app.modules.lms.application.authoring.access import access_to, load_step
from app.modules.lms.application.authoring.uow_factory import UowFactory
from app.modules.lms.application.authoring.views import HtmlWidgetLaunchView
from app.modules.lms.application.html_widget_links import HtmlWidgetLinks
from app.modules.lms.domain.authoring.errors import (
    HtmlWidgetBlockNotFoundError,
    StepNotFoundError,
)
from app.modules.lms.domain.authoring.permissions import VIEW_DRAFTS
from app.modules.lms.domain.step_content import HtmlBlock, StepContent
from app.shared.actor import Actor


class PreviewHtmlWidget:
    """Launch URL of a draft's HTML block; needs `view_drafts` like the preview."""

    def __init__(self, uow_factory: UowFactory, links: HtmlWidgetLinks) -> None:
        """Store the unit of work factory and the link signer."""
        self.uow_factory = uow_factory
        self.links = links

    async def execute(
        self, actor: Actor, course_id: UUID, step_id: UUID, block_id: str
    ) -> HtmlWidgetLaunchView:
        """Return the signed base URL and entry page of the block's widget."""
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
                if isinstance(block, HtmlBlock) and block.id == block_id
            ),
            "",
        )
        if not package_id:
            raise HtmlWidgetBlockNotFoundError(params={"block_id": block_id})
        launch = self.links.launch(course_id, UUID(package_id))
        return HtmlWidgetLaunchView(
            base_url=launch.base_url,
            entry_url=launch.entry_url,
            expires_in=launch.expires_in,
        )
