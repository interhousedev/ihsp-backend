"""Assign or clear the head student (староста) of a group."""

from uuid import UUID

from app.modules.academic.application.schedule.common import UowFactory
from app.modules.academic.application.schedule.update_group import UpdateGroup
from app.modules.academic.domain.schedule.errors import (
    GroupNotFoundError,
    NotGroupMemberError,
)
from app.shared.actor import Actor


class SetHeadStudent:
    """Set the head student; they must be an active member of the group."""

    def __init__(self, uow_factory: UowFactory, update_group: UpdateGroup) -> None:
        """Store the dependencies."""
        self.uow_factory = uow_factory
        self.update_group = update_group

    async def execute(
        self, actor: Actor, group_id: UUID, student_id: UUID | None
    ) -> None:
        """Check membership, then save and audit through ``UpdateGroup``."""
        async with self.uow_factory() as uow:
            group = await uow.groups.get(group_id)
            if group is None:
                raise GroupNotFoundError()
            if student_id is not None:
                student = await uow.students.get(student_id)
                if (
                    student is None
                    or student.group_id != group_id
                    or student.status != "active"
                ):
                    raise NotGroupMemberError(params={"user_id": str(student_id)})
        await self.update_group.execute(actor, group_id, head_student_id=student_id)
