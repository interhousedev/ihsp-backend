"""Adapters of the faces module: students (academic, identity), sniffing, excuses."""

from collections.abc import Callable, Sequence
from datetime import datetime
from uuid import UUID

from app.modules.faces.ports.directory import StudentInfo
from app.shared.contracts.academic import ScheduleQueries
from app.shared.contracts.excuses import ExcuseStatus, ExcuseStatusReader
from app.shared.contracts.identity import IdentityDirectory


class FacesDirectoryAdapter:
    """Students, groups and curators for the entrance."""

    def __init__(self, identity: IdentityDirectory, schedule: ScheduleQueries) -> None:
        """Store the contracts."""
        self.identity = identity
        self.schedule = schedule

    async def student(self, user_id: UUID) -> StudentInfo | None:
        """Return the active student or None."""
        ref = await self.schedule.get_student(user_id)
        if ref is None or ref.status != "active":
            return None
        names = await self.full_names([user_id])
        return StudentInfo(
            user_id=user_id,
            full_name=names.get(user_id, ""),
            group_id=ref.group_id,
            group_name=ref.group_name,
        )

    async def curates(self, teacher_id: UUID, group_id: UUID) -> bool:
        """Return True when the teacher curates the group."""
        return group_id in await self.schedule.curated_group_ids(teacher_id)

    async def full_names(self, user_ids: Sequence[UUID]) -> dict[UUID, str]:
        """Return "Last First" of the users that exist."""
        users = await self.identity.get_users(list(user_ids))
        return {
            uid: f"{u.last_name} {u.first_name}".strip() for uid, u in users.items()
        }


class LazyExcuseStatus:
    """Resolves the excuse reader when first used (academic builds it later)."""

    def __init__(self, resolve: Callable[[], ExcuseStatusReader]) -> None:
        """Store the resolver."""
        self._resolve = resolve

    async def status(self, student_id: UUID, at: datetime) -> ExcuseStatus:
        """Return the student's excuse state."""
        return await self._resolve().status(student_id, at)
