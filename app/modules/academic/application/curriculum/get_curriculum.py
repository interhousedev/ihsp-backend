"""Read the stored EMIS curriculum of a group (for Administration and students)."""

from uuid import UUID

from app.modules.academic.application.curriculum.views import (
    CurriculumView,
    build_curriculum_view,
)
from app.modules.academic.application.schedule.common import UowFactory, today
from app.modules.academic.domain.schedule.errors import GroupNotFoundError
from app.shared.actor import Actor
from app.shared.clock import Clock


class GetGroupCurriculum:
    """Return the curriculum stored for a group."""

    def __init__(self, uow_factory: UowFactory, clock: Clock) -> None:
        """Store the dependencies."""
        self.uow_factory = uow_factory
        self.clock = clock

    async def execute(self, group_id: UUID) -> CurriculumView | None:
        """Return the curriculum, or None when the group has none stored yet."""
        async with self.uow_factory() as uow:
            group = await uow.groups.get(group_id)
            if group is None:
                raise GroupNotFoundError()
            return await build_curriculum_view(uow, group, today(self.clock))


class GetMyCurriculum:
    """Return the curriculum of the student's own group."""

    def __init__(self, uow_factory: UowFactory, clock: Clock) -> None:
        """Store the dependencies."""
        self.uow_factory = uow_factory
        self.clock = clock

    async def execute(self, actor: Actor) -> CurriculumView | None:
        """Return the curriculum, or None for a user without a group or curriculum."""
        async with self.uow_factory() as uow:
            student = await uow.students.get(actor.user_id)
            if student is None:
                return None
            group = await uow.groups.get(student.group_id)
            if group is None:
                return None
            return await build_curriculum_view(uow, group, today(self.clock))
