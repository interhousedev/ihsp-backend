"""Delete a group: its students are moved or detached, the users stay (ADM-6)."""

from uuid import UUID

from app.modules.academic.application.schedule.common import UowFactory
from app.modules.academic.domain.schedule.errors import (
    GroupNotFoundError,
    TargetGroupInvalidError,
)
from app.shared.actor import Actor
from app.shared.notifications import AuditDraft


class DeleteGroup:
    """Remove a group; its students move to another group or become groupless."""

    def __init__(self, uow_factory: UowFactory) -> None:
        """Store the dependencies."""
        self.uow_factory = uow_factory

    async def execute(
        self, actor: Actor, group_id: UUID, move_students_to: UUID | None = None
    ) -> None:
        """Move or detach the students, drop the group's schedule rows and the group."""
        async with self.uow_factory() as uow:
            group = await uow.groups.get(group_id)
            if group is None:
                raise GroupNotFoundError()
            if move_students_to is not None and (
                move_students_to == group_id
                or await uow.groups.get(move_students_to) is None
            ):
                raise TargetGroupInvalidError()
            students = await uow.students.list_filtered(group_id=group_id)
            if move_students_to is not None:
                for student in students:
                    student.move_to(move_students_to)
                    await uow.students.save(student)
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
                        "moved_to_group_id": (
                            str(move_students_to) if move_students_to else None
                        ),
                    },
                )
            )
            await uow.commit()
