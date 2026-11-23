"""Use case: the signed URL of an HTML widget block of a live step."""

from uuid import UUID

from app.modules.lms.application.html_widget_links import HtmlWidgetLinks
from app.modules.lms.application.learning.audience import AudienceGate
from app.modules.lms.application.learning.revision_loading import load_rendered
from app.modules.lms.application.learning.step_context import (
    load_live_step,
    staff_access,
)
from app.modules.lms.application.learning.types import UowFactory
from app.modules.lms.application.learning.views import HtmlWidgetLaunchView
from app.modules.lms.domain.learning.errors import (
    CourseNotFoundError,
    HtmlWidgetNotFoundError,
    NotEnrolledError,
)
from app.modules.lms.domain.learning.live import RenderCache
from app.shared.actor import Actor


class GetHtmlWidgetLaunch:
    """Check enrollment (or staff) and the audience, then sign the widget URL."""

    def __init__(
        self,
        uow_factory: UowFactory,
        cache: RenderCache,
        links: HtmlWidgetLinks,
        gate: AudienceGate,
    ) -> None:
        """Store collaborators."""
        self.uow_factory = uow_factory
        self.cache = cache
        self.links = links
        self.gate = gate

    async def execute(
        self, actor: Actor, course_id: UUID, step_id: UUID, block_id: str
    ) -> HtmlWidgetLaunchView:
        """Return where the frame loads the widget from."""
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
            await self.gate.require_step(uow, actor, course_id, step_id)
            rendered = await load_rendered(
                uow, self.cache, context.live_step.revision_id
            )
        package_id = next(
            (
                block.get("package_id")
                for block in rendered.blocks
                if block["id"] == block_id and block["type"] == "html"
            ),
            None,
        )
        if not package_id:
            raise HtmlWidgetNotFoundError(params={"block_id": block_id})
        launch = self.links.launch(course_id, UUID(package_id))
        return HtmlWidgetLaunchView(
            base_url=launch.base_url,
            entry_url=launch.entry_url,
            expires_in=launch.expires_in,
        )
