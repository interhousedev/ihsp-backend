"""Rename a group, set its semester, curator and head student, or archive it."""

from uuid import UUID

from app.modules.academic.application.schedule.common import UowFactory
from app.modules.academic.application.schedule.group_views import build_group_detail
from app.modules.academic.application.schedule.ports.unit_of_work import (
    ScheduleUnitOfWork,
)
from app.modules.academic.application.schedule.results import GroupDetailData
from app.modules.academic.application.schedule.unset import UNSET, Unset
from app.modules.academic.domain.schedule.errors import (
    CuratorNotTeacherError,
    GroupNameTakenError,
    GroupNotFoundError,
    HeadStudentInvalidError,
)
from app.modules.academic.domain.schedule.group import Group, clean_group_name
from app.shared.actor import Actor, Role
from app.shared.contracts.identity import IdentityDirectory
from app.shared.notifications import AuditDraft


class UpdateGroup:
    """Change the name, semester, curator, head student or status of a group."""

    def __init__(self, uow_factory: UowFactory, identity: IdentityDirectory) -> None:
        """Store the dependencies."""
        self.uow_factory = uow_factory
        self.identity = identity

    async def execute(
        self,
        actor: Actor,
        group_id: UUID,
        *,
        curator_id: UUID | None | Unset = UNSET,
        head_student_id: UUID | None | Unset = UNSET,
        status: str | None = None,
        name: str | None = None,
        current_semester: int | None = None,
    ) -> GroupDetailData:
        """Apply the fields that were sent; None clears curator or head student."""
        async with self.uow_factory() as uow:
            group = await uow.groups.get(group_id)
            if group is None:
                raise GroupNotFoundError()
            if name is not None:
                await self._rename(uow, group, name)
            if current_semester is not None:
                group.current_semester = current_semester
            if not isinstance(curator_id, Unset):
                await self._set_curator(uow, actor, group, curator_id)
            if not isinstance(head_student_id, Unset):
                await self._set_head(uow, actor, group, head_student_id)
            if status is not None and status != group.status:
                await self._set_status(uow, group, status)
            await uow.groups.save(group)
            detail = await build_group_detail(uow, self.identity, group)
            await uow.commit()
        return detail

    @staticmethod
    async def _rename(uow: ScheduleUnitOfWork, group: Group, raw: str) -> None:
        clean, slug = clean_group_name(raw)
        if clean == group.name:
            return
        clash = await uow.groups.find_active_by_slug(slug)
        if clash is not None and clash.id != group.id:
            raise GroupNameTakenError(params={"name": clean})
        group.name, group.slug = clean, slug

    async def _set_curator(
        self,
        uow: ScheduleUnitOfWork,
        actor: Actor,
        group: Group,
        curator_id: UUID | None,
    ) -> None:
        if curator_id is not None:
            user = await self.identity.get_user(curator_id)
            if user is None or Role.TEACHER not in user.roles:
                raise CuratorNotTeacherError(params={"user_id": str(curator_id)})
        if curator_id == group.curator_id:
            return
        previous, group.curator_id = group.curator_id, curator_id
        uow.audit(
            AuditDraft(
                type="group.curator_set",
                user_id=curator_id,
                actor_id=actor.user_id,
                metadata={
                    "group_id": str(group.id),
                    "previous": str(previous) if previous else None,
                },
            )
        )

    async def _set_head(
        self,
        uow: ScheduleUnitOfWork,
        actor: Actor,
        group: Group,
        head_student_id: UUID | None,
    ) -> None:
        if head_student_id is not None:
            student = await uow.students.get(head_student_id)
            if (
                student is None
                or student.group_id != group.id
                or student.status != "active"
            ):
                raise HeadStudentInvalidError(params={"user_id": str(head_student_id)})
        if head_student_id == group.head_student_id:
            return
        previous, group.head_student_id = group.head_student_id, head_student_id
        uow.audit(
            AuditDraft(
                type="group.head_student_set",
                user_id=head_student_id,
                actor_id=actor.user_id,
                metadata={
                    "group_id": str(group.id),
                    "previous": str(previous) if previous else None,
                },
            )
        )

    @staticmethod
    async def _set_status(uow: ScheduleUnitOfWork, group: Group, status: str) -> None:
        if status == "active":
            clash = await uow.groups.find_active_by_slug(group.slug)
            if clash is not None and clash.id != group.id:
                raise GroupNameTakenError(params={"name": group.name})
            group.status = "active"
        else:
            group.status = "archived"
