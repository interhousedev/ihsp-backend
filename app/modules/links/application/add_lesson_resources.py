"""Attach a URL or a file to one or more lessons (ACA-9, UF-WEB-07, UF-STF-04)."""

from collections.abc import Sequence
from uuid import UUID

from app.modules.links.application.lesson_access import LessonAccess, LessonViewer
from app.modules.links.application.link_creation_limit import LinkCreationLimit
from app.modules.links.application.resource_builder import ResourceBuilder
from app.modules.links.application.room_cache_invalidator import RoomCacheInvalidator
from app.modules.links.application.slug_allocator import SlugAllocator
from app.modules.links.application.target_resolver import (
    ResolvedTarget,
    TargetResolver,
)
from app.modules.links.application.views import ResourceView
from app.modules.links.domain.errors import (
    InvalidLinkTargetError,
    LessonMismatchError,
    LessonWindowClosedError,
    ResourceForbiddenError,
)
from app.modules.links.domain.lesson_policy import (
    MAX_EXTRA_LESSONS,
    student_window_open,
)
from app.modules.links.domain.link import LessonRole, Link, LinkKind
from app.modules.links.ports.unit_of_work import LinksUnitOfWork, UowFactory
from app.shared.actor import Actor, Role
from app.shared.clock import Clock, local_today
from app.shared.contracts.academic import LessonRef, ScheduleQueries
from app.shared.ids import new_id


class AddLessonResources:
    """Create one lesson resource link per lesson, all pointing to the same target."""

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        access: LessonAccess,
        schedule: ScheduleQueries,
        resolver: TargetResolver,
        allocator: SlugAllocator,
        limit: LinkCreationLimit,
        builder: ResourceBuilder,
        invalidator: RoomCacheInvalidator,
        clock: Clock,
    ) -> None:
        """Initialize the use case."""
        self.uow_factory = uow_factory
        self.access = access
        self.schedule = schedule
        self.resolver = resolver
        self.allocator = allocator
        self.limit = limit
        self.builder = builder
        self.invalidator = invalidator
        self.clock = clock

    async def execute(
        self,
        actor: Actor,
        lesson_id: UUID,
        *,
        role: LessonRole,
        kind: LinkKind,
        target_url: str | None = None,
        file_id: UUID | None = None,
        also_lesson_ids: Sequence[UUID] = (),
    ) -> list[ResourceView]:
        """Check permissions and the target, then create the links."""
        if role is LessonRole.HOMEWORK:
            raise InvalidLinkTargetError(params={"role": role.value})
        lesson = await self.access.lesson(lesson_id)
        await self._check_permission(actor, lesson, role)
        extras = await self._extra_lessons(actor, lesson, also_lesson_ids)
        await self.limit.hit(actor.user_id)
        target = await self.resolver.resolve(
            actor, kind=kind, target_url=target_url, file_id=file_id
        )
        lessons = [lesson, *extras]
        async with self.uow_factory() as uow:
            links = [
                await self._attach(uow, actor, item, role, target) for item in lessons
            ]
            await uow.commit()
        for item in lessons:
            await self.invalidator.lesson(item)
        return await self.builder.resources(links)

    async def _check_permission(
        self, actor: Actor, lesson: LessonRef, role: LessonRole
    ) -> None:
        viewer = await self.access.viewer(actor, lesson)
        if viewer is LessonViewer.MANAGER:
            return
        if role is not LessonRole.ATTACHMENT:
            raise ResourceForbiddenError(params={"role": role.value})
        if not student_window_open(lesson.date, local_today(self.clock)):
            raise LessonWindowClosedError(params={"date": lesson.date.isoformat()})

    async def _extra_lessons(
        self, actor: Actor, lesson: LessonRef, ids: Sequence[UUID]
    ) -> list[LessonRef]:
        wanted = [item for item in dict.fromkeys(ids) if item != lesson.id]
        if not wanted:
            return []
        if not actor.has(Role.TEACHER) or len(wanted) > MAX_EXTRA_LESSONS:
            raise ResourceForbiddenError(support_details="also_lesson_ids")
        if not await self.schedule.is_lesson_teacher(actor.user_id, lesson.id):
            raise ResourceForbiddenError(support_details="also_lesson_ids")
        return [await self._extra(actor, lesson, item) for item in wanted]

    async def _extra(self, actor: Actor, main: LessonRef, lesson_id: UUID) -> LessonRef:
        other = await self.access.lesson(lesson_id)
        if other.subject_id != main.subject_id or other.date != main.date:
            raise LessonMismatchError(params={"lesson_id": str(lesson_id)})
        if not await self.schedule.is_lesson_teacher(actor.user_id, other.id):
            raise ResourceForbiddenError(params={"lesson_id": str(lesson_id)})
        return other

    async def _attach(
        self,
        uow: LinksUnitOfWork,
        actor: Actor,
        lesson: LessonRef,
        role: LessonRole,
        target: ResolvedTarget,
    ) -> Link:
        existing = await uow.links.list_for_lessons([lesson.id])
        for link in existing:
            if _same(link, actor, role, target):
                return link
        now = self.clock.now()

        def build(slug: str) -> Link:
            return Link(
                id=new_id(),
                slug=slug,
                kind=target.kind,
                owner_id=actor.user_id,
                created_at=now,
                target_url=target.target_url,
                file_id=target.file_id,
                title=target.title,
                lesson_id=lesson.id,
                lesson_role=role,
            )

        return await self.allocator.add(uow, build, kind=target.kind)


def _same(link: Link, actor: Actor, role: LessonRole, target: ResolvedTarget) -> bool:
    return (
        link.owner_id == actor.user_id
        and link.lesson_role is role
        and link.target_url == target.target_url
        and link.file_id == target.file_id
    )
