"""Building TimetableEntry read models with names."""

from collections.abc import Sequence
from uuid import UUID

from app.modules.academic.application.schedule.common import (
    person_map,
    subject_data,
)
from app.modules.academic.application.schedule.ports.unit_of_work import (
    ScheduleUnitOfWork,
)
from app.modules.academic.application.schedule.results import (
    AudienceItemData,
    RoomLiteData,
    TimetableEntryData,
)
from app.modules.academic.domain import audience as audience_keys
from app.modules.academic.domain.schedule.group import Group
from app.modules.academic.domain.schedule.timetable_entry import TimetableEntry
from app.shared.contracts.identity import IdentityDirectory


async def build_entry_data(
    uow: ScheduleUnitOfWork,
    identity: IdentityDirectory,
    entries: Sequence[TimetableEntry],
    locale: str,
) -> list[TimetableEntryData]:
    """Resolve subject, teacher, room and group names for the entries."""
    subjects = await uow.subjects.get_many({e.subject_id for e in entries})
    rooms = await uow.rooms.get_many({e.room_id for e in entries if e.room_id})
    group_ids = {g for e in entries for g in audience_keys.group_ids(e.audience)}
    groups = await uow.groups.get_many(group_ids)
    people = await person_map(identity, [e.teacher_id for e in entries])
    result: list[TimetableEntryData] = []
    for entry in entries:
        room = rooms.get(entry.room_id) if entry.room_id else None
        result.append(
            TimetableEntryData(
                id=entry.id,
                term_id=entry.term_id,
                weekday=entry.weekday,
                period=entry.period,
                week_parity=entry.week_parity,
                subject=subject_data(subjects[entry.subject_id], locale),
                teacher=people.get(entry.teacher_id) if entry.teacher_id else None,
                room=RoomLiteData(room.id, room.slug, room.name) if room else None,
                audience=_audience(entry.audience, groups),
                valid_from=entry.valid_from,
                valid_to=entry.valid_to,
            )
        )
    return result


def _audience(keys: Sequence[str], groups: dict[UUID, Group]) -> list[AudienceItemData]:
    items: list[AudienceItemData] = []
    for key in keys:
        group_id, subgroup = audience_keys.parse(key)
        group = groups.get(group_id)
        items.append(
            AudienceItemData(group_id, group.name if group else str(group_id), subgroup)
        )
    return items
