"""Delete a group: its students become groupless, the users stay (ADM-6)."""

from uuid import UUID

from app.modules.academic.application.schedule.common import UowFactory
from app.modules.academic.domain.schedule.errors import GroupNotFoundError
from app.shared.actor import Actor
from app.shared.notifications import AuditDraft


class DeleteGroup:
    """Remove a group and detach its students."""

    def __init__(self, uow_factory: UowFactory) -> None:
        """Store the dependencies."""
        self.uow_factory = uow_factory

    async def execute(self, actor: Actor, group_id: UUID) -> None:
        """Detach the students, drop the group's schedule rows and the group."""
        async with self.uow_factory() as uow:
            group = await uow.groups.get(group_id)
            if group is None:
                raise GroupNotFoundError()
            students = await uow.students.list_filtered(group_id=group_id)
            await uow.groups.delete(group_id)
            uow.audit(
                AuditDraft(
                    type="group.deleted",
                    user_id=None,
                    actor_id=actor.user_id,
                    metadata={
                        "group_id": str(group.id),
                        "name": group.name,
                        "student_count": len(students),
                        "student_ids": [str(s.user_id) for s in students],
                    },
                )
            )
            await uow.commit()
