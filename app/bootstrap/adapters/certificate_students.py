"""Adapter: the certificates module's `StudentDirectory` over the academic schedule."""

from collections.abc import Sequence
from uuid import UUID

from app.modules.academic.application.schedule.results import StudentItemData
from app.modules.academic.wiring_schedule import ScheduleServices
from app.modules.certificates.ports.student_directory import GroupInfo, StudentInfo

PAGE = 100


def _info(item: StudentItemData) -> StudentInfo | None:
    if item.group_id is None or item.group_name is None:
        return None
    return StudentInfo(
        id=item.user_id,
        name=f"{item.last_name} {item.first_name}".strip(),
        group_id=item.group_id,
        group_name=item.group_name,
        subgroup=None if item.subgroup is None else str(item.subgroup),
    )


class CertificateStudentsAdapter:
    """Active students, groups and curators for certificates, read from academic."""

    def __init__(self, schedule: ScheduleServices) -> None:
        """Store the schedule services."""
        self.schedule = schedule

    async def student(self, user_id: UUID) -> StudentInfo | None:
        """Return the active student or None."""
        ref = await self.schedule.queries.get_student(user_id)
        if ref is None or ref.status != "active":
            return None
        found = await self.students([ref.group_id])
        return next((s for s in found if s.id == user_id), None)

    async def students(
        self,
        group_ids: Sequence[UUID] | None,
        *,
        subgroup: str | None = None,
        query: str | None = None,
    ) -> list[StudentInfo]:
        """Return active students of the groups (None: every group), by name."""
        if subgroup is not None and not subgroup.isdigit():
            return []
        number = None if subgroup is None else int(subgroup)
        wanted: Sequence[UUID | None] = [None] if group_ids is None else group_ids
        found: list[StudentInfo] = []
        for group_id in wanted:
            found.extend(await self._pages(group_id, number, query))
        return found

    async def groups(self, group_ids: Sequence[UUID] | None) -> list[GroupInfo]:
        """Return active groups by name with their subgroups; None means all."""
        items = await self.schedule.list_groups.execute("active")
        keep = None if group_ids is None else set(group_ids)
        everyone = await self.students(group_ids)
        subgroups: dict[UUID, set[str]] = {}
        for student in everyone:
            if student.subgroup is not None:
                subgroups.setdefault(student.group_id, set()).add(student.subgroup)
        return [
            GroupInfo(g.id, g.name, tuple(sorted(subgroups.get(g.id, ()))))
            for g in items
            if keep is None or g.id in keep
        ]

    async def curated_group_ids(self, teacher_id: UUID) -> list[UUID]:
        """Return ids of the groups the teacher curates."""
        return await self.schedule.queries.curated_group_ids(teacher_id)

    async def _pages(
        self, group_id: UUID | None, subgroup: int | None, query: str | None
    ) -> list[StudentInfo]:
        out: list[StudentInfo] = []
        cursor: str | None = None
        while True:
            page = await self.schedule.list_students.execute(
                query=query,
                group_id=group_id,
                subgroup=subgroup,
                status="active",
                cursor=cursor,
                limit=PAGE,
            )
            out.extend(i for i in map(_info, page.items) if i is not None)
            cursor = page.next_cursor
            if cursor is None:
                return out
