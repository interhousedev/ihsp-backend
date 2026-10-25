"""Hide or show a lesson resource (STF-6, UF-STF-08)."""

from uuid import UUID

from app.modules.links.application.lesson_access import LessonAccess, LessonViewer
from app.modules.links.application.resource_builder import ResourceBuilder
from app.modules.links.application.room_cache_invalidator import RoomCacheInvalidator
from app.modules.links.application.views import ResourceView
from app.modules.links.domain.errors import LinkNotFoundError, ResourceForbiddenError
from app.modules.links.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from app.shared.clock import Clock


class HideLessonResource:
    """The lesson's teacher or an admin hides a resource from students and rooms."""

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        access: LessonAccess,
        builder: ResourceBuilder,
        invalidator: RoomCacheInvalidator,
        clock: Clock,
    ) -> None:
        """Initialize the use case."""
        self.uow_factory = uow_factory
        self.access = access
        self.builder = builder
        self.invalidator = invalidator
        self.clock = clock

    async def execute(
        self, actor: Actor, lesson_id: UUID, link_id: UUID, *, hidden: bool
    ) -> ResourceView:
        """Set or clear the hidden flag."""
        lesson = await self.access.lesson(lesson_id)
        if await self.access.viewer(actor, lesson) is not LessonViewer.MANAGER:
            raise ResourceForbiddenError(params={"lesson_id": str(lesson_id)})
        async with self.uow_factory() as uow:
            link = await uow.links.get(link_id)
            if link is None or link.lesson_id != lesson_id or link.is_revoked:
                raise LinkNotFoundError(params={"link_id": str(link_id)})
            if hidden:
                link.hide(actor.user_id, self.clock.now())
            else:
                link.unhide()
            await uow.links.save(link)
            await uow.commit()
        await self.invalidator.lesson(lesson)
        return (await self.builder.resources([link]))[0]
