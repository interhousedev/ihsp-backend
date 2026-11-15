"""Set or change the group of one student (Administration)."""

from uuid import UUID

from app.modules.academic.application.schedule.common import UowFactory
from app.modules.academic.domain.schedule.errors import (
    GroupNotFoundError,
    StudentNotFoundError,
)
from app.shared.actor import Actor
from app.shared.notifications import AuditDraft


class SetStudentGroup:
    """Move a student to a group, or detach them with None."""

    def __init__(self, uow_factory: UowFactory) -> None:
        """Store the dependencies."""
        self.uow_factory = uow_factory

    async def execute(self, actor: Actor, user_id: UUID, group_id: UUID | None) -> None:
        """Change the group; the subgroup resets when the group changes."""
        async with self.uow_factory() as uow:
            student = await uow.students.get(user_id)
            if student is None:
                raise StudentNotFoundError()
            if group_id is not None and await uow.groups.get(group_id) is None:
                raise GroupNotFoundError()
            previous = student.group_id
            if previous == group_id:
                return
            if group_id is None:
                student.group_id = None
                student.subgroup = None
                student.subgroup_set_by = None
                student.subgroup_set_at = None
            else:
                student.move_to(group_id)
            await uow.students.save(student)
            uow.audit(
                AuditDraft(
                    type="student.group_changed",
                    user_id=user_id,
                    actor_id=actor.user_id,
                    metadata={
                        "from_group_id": str(previous) if previous else None,
                        "to_group_id": str(group_id) if group_id else None,
                    },
                )
            )
            await uow.commit()
