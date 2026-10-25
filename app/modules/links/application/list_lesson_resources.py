"""List the resources of a lesson (ACA-9, UF-WEB-06)."""

from uuid import UUID

from app.modules.links.application.lesson_access import LessonAccess, LessonViewer
from app.modules.links.application.resource_builder import ResourceBuilder
from app.modules.links.application.views import ResourceView
from app.modules.links.domain.link import LessonRole
from app.modules.links.ports.unit_of_work import UowFactory
from app.shared.actor import Actor


class ListLessonResources:
    """Teachers and admins see everything; students see visible ones and their own."""

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        access: LessonAccess,
        builder: ResourceBuilder,
    ) -> None:
        """Initialize the use case."""
        self.uow_factory = uow_factory
        self.access = access
        self.builder = builder

    async def execute(self, actor: Actor, lesson_id: UUID) -> list[ResourceView]:
        """Return the lesson's resources, materials first."""
        lesson = await self.access.lesson(lesson_id)
        viewer = await self.access.viewer(actor, lesson)
        async with self.uow_factory() as uow:
            links = await uow.links.list_for_lessons([lesson_id])
        manager = viewer is LessonViewer.MANAGER
        visible = [
            link
            for link in links
            if not link.is_disabled
            and (manager or not link.is_hidden or link.owner_id == actor.user_id)
        ]
        views = await self.builder.resources(visible)
        return sorted(
            views, key=lambda view: view.link.lesson_role is not LessonRole.MATERIAL
        )
