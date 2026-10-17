"""Which students a staff member may see: all for Administration, own groups else."""

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from app.modules.certificates.domain.errors import NotCuratorError
from app.modules.certificates.ports.student_directory import (
    GroupInfo,
    StudentDirectory,
    StudentInfo,
)
from app.shared.actor import Actor, Role


@dataclass(frozen=True, slots=True)
class StaffFilters:
    """Query filters of the staff views."""

    group_id: UUID | None = None
    subgroup: str | None = None
    type_id: UUID | None = None
    subject: str | None = None
    level: str | None = None
    student_id: UUID | None = None
    q: str | None = None


class StaffScope:
    """Resolves the students and groups a caller may see."""

    def __init__(self, *, directory: StudentDirectory) -> None:
        """Store the dependencies."""
        self._directory = directory

    async def allowed_groups(self, actor: Actor) -> list[UUID] | None:
        """Return the curated group ids; None for Administration (every group)."""
        if actor.has(Role.ADMIN):
            return None
        groups = await self._directory.curated_group_ids(actor.user_id)
        if not groups:
            raise NotCuratorError()
        return groups

    async def groups(self, actor: Actor) -> list[GroupInfo]:
        """Return the groups the caller may see."""
        return await self._directory.groups(await self.allowed_groups(actor))

    async def students(self, actor: Actor, flt: StaffFilters) -> list[StudentInfo]:
        """Return the students inside the caller's scope that match the filters."""
        allowed = await self.allowed_groups(actor)
        groups = self._wanted_groups(allowed, flt.group_id)
        found = await self._directory.students(
            groups, subgroup=flt.subgroup, query=flt.q
        )
        if flt.student_id is None:
            return found
        await self._check_student(allowed, flt.student_id)
        return [s for s in found if s.id == flt.student_id]

    async def student_in_scope(self, actor: Actor, student_id: UUID) -> StudentInfo:
        """Return the student, or raise when the caller may not see them."""
        allowed = await self.allowed_groups(actor)
        info = await self._directory.student(student_id)
        if info is None or (allowed is not None and info.group_id not in allowed):
            raise NotCuratorError()
        return info

    @staticmethod
    def _wanted_groups(
        allowed: Sequence[UUID] | None, group_id: UUID | None
    ) -> Sequence[UUID] | None:
        if group_id is None:
            return allowed
        if allowed is not None and group_id not in allowed:
            raise NotCuratorError()
        return [group_id]

    async def _check_student(
        self, allowed: Sequence[UUID] | None, student_id: UUID
    ) -> None:
        if allowed is None:
            return
        info = await self._directory.student(student_id)
        if info is not None and info.group_id not in allowed:
            raise NotCuratorError()
