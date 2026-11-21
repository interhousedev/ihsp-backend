"""When each university on a student's list wants the application."""

import datetime as dt
from dataclasses import dataclass
from uuid import UUID

from app.modules.admission.ports.unit_of_work import AdmissionUnitOfWork


@dataclass(frozen=True, slots=True)
class DueDate:
    """An application due instant; `predicted` when the date is not confirmed."""

    due_utc: dt.datetime
    predicted: bool


def earliest(dues: list[DueDate]) -> DueDate | None:
    """The soonest of the dates, or None."""
    return min(dues, key=lambda d: d.due_utc, default=None)


async def application_dues(
    uow: AdmissionUnitOfWork, student_id: UUID
) -> dict[UUID, DueDate]:
    """The earliest dated application milestone of each listed university."""
    entries = await uow.shortlist.entries(student_id)
    by_entry = {e.id: e.institution_id for e in entries}
    found: dict[UUID, list[DueDate]] = {}
    for m in await uow.deadlines.milestones_of_entries(list(by_entry)):
        if m.kind == "application" and m.due_utc is not None:
            found.setdefault(by_entry[m.list_entry_id], []).append(
                DueDate(m.due_utc, m.predicted)
            )
    return {i: d for i, ds in found.items() if (d := earliest(ds)) is not None}
