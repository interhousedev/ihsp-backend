"""Generate the checklist rows of a student (§12.1); safe to run again."""

from uuid import UUID

from app.modules.admission.domain.checklist import entry_items, shared_items
from app.modules.admission.domain.chooser import ListEntry
from app.modules.admission.ports.unit_of_work import AdmissionUnitOfWork


async def ensure_shared(uow: AdmissionUnitOfWork, student_id: UUID) -> None:
    """Create the student-level rows that are missing."""
    existing = await uow.checklist.for_student(student_id)
    await uow.checklist.ensure(shared_items(student_id, existing))


async def ensure_entry(uow: AdmissionUnitOfWork, entry: ListEntry) -> None:
    """Create the rows of one list entry for its round that are missing."""
    existing = await uow.checklist.for_student(entry.student_id)
    deadlines = await uow.deadlines.current(institution_id=entry.institution_id)
    await uow.checklist.ensure(entry_items(entry, existing, deadlines))


async def ensure_all(uow: AdmissionUnitOfWork, student_id: UUID) -> None:
    """Create every missing row for the profile and each live list entry."""
    await ensure_shared(uow, student_id)
    for entry in await uow.shortlist.entries(student_id):
        await ensure_entry(uow, entry)
