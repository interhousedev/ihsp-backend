"""Building and checking timetable entries before they are saved."""

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from app.modules.academic.application.schedule.ensure_room import (
    ensure_room_in,
    find_room_in,
)
from app.modules.academic.application.schedule.ports.unit_of_work import (
    ScheduleUnitOfWork,
)
from app.modules.academic.domain.schedule.audience_display import keys_from_input
from app.modules.academic.domain.schedule.conflicts import Conflict, entry_conflicts
from app.modules.academic.domain.schedule.errors import (
    EntryInvalidError,
    GroupNotFoundError,
    SubjectNotFoundError,
    TermNotFoundError,
)
from app.modules.academic.domain.schedule.timetable_entry import (
    TimetableEntry,
    WeekParity,
    validate_entry,
)
from app.shared.base_error import ConflictError
from app.shared.ids import new_id


@dataclass(frozen=True, slots=True)
class EntryInput:
    """Everything a timetable entry needs, with the room as a typed name."""

    term_id: UUID
    weekday: int
    period: int
    week_parity: WeekParity
    subject_id: UUID
    teacher_id: UUID | None
    room_name: str | None
    audience: Sequence[tuple[UUID, int | None]]
    valid_from: dt.date
    valid_to: dt.date | None


async def check_references(
    uow: ScheduleUnitOfWork, entry: TimetableEntry, groups: Sequence[UUID]
) -> None:
    """Raise unless the term, subject and groups of the entry exist."""
    if await uow.terms.get(entry.term_id) is None:
        raise TermNotFoundError()
    if await uow.subjects.get(entry.subject_id) is None:
        raise SubjectNotFoundError()
    found = await uow.groups.get_many(set(groups))
    missing = set(groups) - set(found)
    if missing:
        raise GroupNotFoundError(params={"group_ids": sorted(str(g) for g in missing)})


async def resolve_room_id(
    uow: ScheduleUnitOfWork, name: str | None, now: dt.datetime, *, create: bool
) -> UUID | None:
    """Return the room of a typed name; create it only when asked to."""
    if name is None or not name.strip():
        return None
    if create:
        return (await ensure_room_in(uow, name, now)).id
    room = await find_room_in(uow, name)
    return room.id if room else None


async def build_entry(
    uow: ScheduleUnitOfWork,
    data: EntryInput,
    *,
    now: dt.datetime,
    create_room: bool,
    entry_id: UUID | None = None,
) -> TimetableEntry:
    """Validate the input and return the entry (not yet saved)."""
    if not data.audience:
        raise EntryInvalidError(params={"reason": "audience"})
    entry = TimetableEntry(
        id=entry_id or new_id(),
        term_id=data.term_id,
        weekday=data.weekday,
        period=data.period,
        week_parity=data.week_parity,
        subject_id=data.subject_id,
        teacher_id=data.teacher_id,
        room_id=await resolve_room_id(uow, data.room_name, now, create=create_room),
        audience=keys_from_input(data.audience),
        valid_from=data.valid_from,
        valid_to=data.valid_to,
    )
    validate_entry(entry)
    await check_references(uow, entry, [group for group, _ in data.audience])
    return entry


async def conflicts_for(
    uow: ScheduleUnitOfWork, entry: TimetableEntry
) -> list[Conflict]:
    """Return the conflicts of an entry with the rest of its term."""
    others = await uow.entries.same_slot(entry.term_id, entry.weekday, entry.period)
    return entry_conflicts(entry, others)


def raise_if_conflicts(conflicts: Sequence[Conflict]) -> None:
    """Raise a ConflictError carrying every conflict (ACA-8)."""
    if conflicts:
        raise ConflictError(params={"conflicts": [c.to_json() for c in conflicts]})
