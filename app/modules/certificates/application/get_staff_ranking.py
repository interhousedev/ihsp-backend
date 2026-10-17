"""Students ranked by how many certificates they have."""

from collections import Counter
from dataclasses import dataclass
from uuid import UUID

from app.modules.certificates.application.list_staff_entries import repo_filter
from app.modules.certificates.application.staff_scope import StaffFilters, StaffScope
from app.modules.certificates.ports.unit_of_work import UowFactory
from app.shared.actor import Actor

MAX_LIMIT = 200


@dataclass(frozen=True, slots=True)
class RankedStudent:
    """A student and their number of certificates."""

    student_id: UUID
    name: str
    group_name: str
    count: int


class GetStaffRanking:
    """Top students by number of certificates matching the filters."""

    def __init__(self, *, uow_factory: UowFactory, scope: StaffScope) -> None:
        """Store the dependencies."""
        self._uow_factory = uow_factory
        self._scope = scope

    async def execute(
        self, actor: Actor, flt: StaffFilters, *, limit: int
    ) -> list[RankedStudent]:
        """Return up to ``limit`` students with at least one certificate."""
        students = await self._scope.students(actor, flt)
        by_id = {s.id: s for s in students}
        async with self._uow_factory() as uow:
            rows, _ = await uow.entries.query(
                repo_filter(students, flt), limit=None, offset=0
            )
        counts = Counter(row.student_id for row in rows)
        ranked = [
            RankedStudent(sid, by_id[sid].name, by_id[sid].group_name, count)
            for sid, count in counts.items()
        ]
        ranked.sort(key=lambda r: (-r.count, r.name.casefold(), str(r.student_id)))
        return ranked[: max(1, min(limit, MAX_LIMIT))]
