"""Staff list of certificates with the student of each."""

from dataclasses import dataclass

from app.modules.certificates.application.staff_scope import StaffFilters, StaffScope
from app.modules.certificates.domain.entry import CertificateEntry
from app.modules.certificates.ports.entry_repository import EntryFilter
from app.modules.certificates.ports.student_directory import StudentInfo
from app.modules.certificates.ports.unit_of_work import UowFactory
from app.shared.actor import Actor

MAX_LIMIT = 200


@dataclass(frozen=True, slots=True)
class StaffEntryView:
    """An entry and the student it belongs to."""

    entry: CertificateEntry
    student: StudentInfo


@dataclass(frozen=True, slots=True)
class StaffEntriesPage:
    """One page of staff entries and the total over all pages."""

    items: list[StaffEntryView]
    total: int


def repo_filter(students: list[StudentInfo], flt: StaffFilters) -> EntryFilter:
    """The repository filter for the students in scope and the query filters."""
    return EntryFilter(
        student_ids=[s.id for s in students],
        type_id=flt.type_id,
        subject=flt.subject,
        level=flt.level,
    )


class ListStaffEntries:
    """Entries of the students the caller may see, newest first."""

    def __init__(self, *, uow_factory: UowFactory, scope: StaffScope) -> None:
        """Store the dependencies."""
        self._uow_factory = uow_factory
        self._scope = scope

    async def execute(
        self, actor: Actor, flt: StaffFilters, *, limit: int, offset: int
    ) -> StaffEntriesPage:
        """Return one page and the total."""
        students = await self._scope.students(actor, flt)
        by_id = {s.id: s for s in students}
        async with self._uow_factory() as uow:
            rows, total = await uow.entries.query(
                repo_filter(students, flt),
                limit=max(1, min(limit, MAX_LIMIT)),
                offset=max(0, offset),
            )
        items = [StaffEntryView(row, by_id[row.student_id]) for row in rows]
        return StaffEntriesPage(items=items, total=total)
