"""Delete a lesson resource (UF-WEB-08)."""

from uuid import UUID

from app.modules.links.application.lesson_access import LessonAccess
from app.modules.links.application.room_cache_invalidator import RoomCacheInvalidator
from app.modules.links.domain.errors import LinkNotFoundError, ResourceForbiddenError
from app.modules.links.ports.unit_of_work import UowFactory
from app.shared.actor import Actor, Role
from app.shared.clock import Clock


class DeleteLessonResource:
    """The author or an admin removes a resource; its short link answers 410."""

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        access: LessonAccess,
        invalidator: RoomCacheInvalidator,
        clock: Clock,
    ) -> None:
        """Initialize the use case."""
        self.uow_factory = uow_factory
        self.access = access
        self.invalidator = invalidator
        self.clock = clock

    async def execute(self, actor: Actor, lesson_id: UUID, link_id: UUID) -> None:
        """Revoke the link; the file stays in My files."""
        lesson = await self.access.lesson(lesson_id)
        async with self.uow_factory() as uow:
            link = await uow.links.get(link_id)
            if link is None or link.lesson_id != lesson_id or link.is_revoked:
                raise LinkNotFoundError(params={"link_id": str(link_id)})
            if link.owner_id != actor.user_id and not actor.has(Role.ADMIN):
                raise ResourceForbiddenError(params={"link_id": str(link_id)})
            link.revoke(self.clock.now())
            await uow.links.save(link)
            await uow.commit()
        await self.invalidator.lesson(lesson)
