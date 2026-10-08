"""Assign students to subgroup 1 or 2, one by one or in bulk (STF-12, UF-STF-10)."""

from collections.abc import Sequence
from uuid import UUID

from app.modules.academic.application.schedule.common import UowFactory
from app.modules.academic.application.schedule.group_access import (
    ensure_curator_or_admin,
)
from app.modules.academic.application.schedule.group_views import build_group_detail
from app.modules.academic.application.schedule.results import GroupDetailData
from app.modules.academic.domain.schedule.errors import (
    GroupNotFoundError,
    SubgroupAssignmentInvalidError,
)
from app.shared.actor import Actor
from app.shared.clock import Clock
from app.shared.contracts.identity import IdentityDirectory
from app.shared.notifications import AuditDraft

SUBGROUPS = (1, 2)


class AssignSubgroups:
    """Set the subgroup of students; only the curator or Administration may."""

    def __init__(
        self, uow_factory: UowFactory, identity: IdentityDirectory, clock: Clock
    ) -> None:
        """Store the dependencies."""
        self.uow_factory = uow_factory
        self.identity = identity
        self.clock = clock

    async def execute(
        self,
        actor: Actor,
        group_id: UUID,
        assignments: Sequence[tuple[UUID, int | None]],
    ) -> GroupDetailData:
        """Apply the assignments and return the group; None clears a subgroup."""
        async with self.uow_factory() as uow:
            group = await uow.groups.get(group_id)
            if group is None:
                raise GroupNotFoundError()
            ensure_curator_or_admin(actor, group)
            students = await uow.students.get_many([uid for uid, _ in assignments])
            now = self.clock.now()
            for user_id, subgroup in assignments:
                student = students.get(user_id)
                if (
                    student is None
                    or student.group_id != group.id
                    or student.status != "active"
                    or (subgroup is not None and subgroup not in SUBGROUPS)
                ):
                    raise SubgroupAssignmentInvalidError(
                        params={"user_id": str(user_id)}
                    )
                if student.subgroup == subgroup:
                    continue
                previous = student.subgroup
                student.assign_subgroup(subgroup, by=actor.user_id, now=now)
                await uow.students.save(student)
                uow.audit(
                    AuditDraft(
                        type="subgroup.assigned",
                        user_id=user_id,
                        actor_id=actor.user_id,
                        metadata={
                            "group_id": str(group.id),
                            "subgroup": subgroup,
                            "previous": previous,
                        },
                    )
                )
            detail = await build_group_detail(uow, self.identity, group)
            await uow.commit()
        return detail
