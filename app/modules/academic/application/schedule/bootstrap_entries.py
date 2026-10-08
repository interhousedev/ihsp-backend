"""Turn the rows of an EMIS timetable into timetable entries of one group."""

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from app.modules.academic.application.schedule.bootstrap_teachers import (
    TeacherResolver,
)
from app.modules.academic.application.schedule.ensure_room import ensure_room_in
from app.modules.academic.application.schedule.ports.unit_of_work import (
    ScheduleUnitOfWork,
)
from app.modules.academic.domain import audience as audience_keys
from app.modules.academic.domain.schedule.conflicts import entry_conflicts
from app.modules.academic.domain.schedule.entry_merge import merge_target
from app.modules.academic.domain.schedule.group import Group
from app.modules.academic.domain.schedule.subject import LANGUAGES, Subject
from app.modules.academic.domain.schedule.term import Term
from app.modules.academic.domain.schedule.timetable_entry import (
    WEEKDAYS,
    TimetableEntry,
    validate_entry,
)
from app.shared.contracts.emis import EmisTimetableItem
from app.shared.ids import new_id

import structlog

log = structlog.get_logger(__name__)

MAX_PERIOD = 20


@dataclass(slots=True)
class ImportTally:
    """What an import did with the rows."""

    entries: int = 0
    merged: int = 0
    skipped: int = 0


class EntryImporter:
    """Writes the rows of one group's timetable inside an open transaction."""

    def __init__(
        self,
        uow: ScheduleUnitOfWork,
        *,
        term: Term,
        group: Group,
        teachers: TeacherResolver,
        now: dt.datetime,
    ) -> None:
        """Bind to the transaction, the term, the group and the teacher resolver."""
        self._uow = uow
        self._term = term
        self._group = group
        self._teachers = teachers
        self._now = now
        self._subjects: dict[tuple[int | None, str], Subject] = {}

    async def run(self, items: Sequence[EmisTimetableItem]) -> ImportTally:
        """Create an entry per usable row; clashes merge or are skipped, never fail."""
        tally = ImportTally()
        for item in items:
            entry = await self._entry_for(item)
            if entry is None:
                tally.skipped += 1
            else:
                await self._place(entry, tally)
        return tally

    async def _entry_for(self, item: EmisTimetableItem) -> TimetableEntry | None:
        period = item.pair_number + 1
        usable = item.weekday in WEEKDAYS and 1 <= period <= MAX_PERIOD
        if not usable or not (item.subject_name.strip() or item.subject_emis_id):
            log.warning("emis_timetable_row_skipped", row=_describe(item))
            return None
        subject = await self._subject(item)
        entry = TimetableEntry(
            id=new_id(),
            term_id=self._term.id,
            weekday=item.weekday,
            period=period,
            week_parity=item.week_parity,
            subject_id=subject.id,
            teacher_id=await self._teachers.resolve(item.teacher),
            room_id=await self._room(item.room),
            audience=[audience_keys.key(self._group.id, item.subgroup)],
            valid_from=self._term.starts_on,
        )
        validate_entry(entry)
        return entry

    async def _place(self, entry: TimetableEntry, tally: ImportTally) -> None:
        others = await self._uow.entries.same_slot(
            entry.term_id, entry.weekday, entry.period
        )
        if not entry_conflicts(entry, others):
            await self._uow.entries.add(entry)
            tally.entries += 1
            return
        target = merge_target(entry, others)
        if target is None:
            log.warning(
                "emis_timetable_row_skipped", reason="conflict", slot=_slot(entry)
            )
            tally.skipped += 1
            return
        target.audience = [*target.audience, *entry.audience]
        await self._uow.entries.save(target)
        tally.merged += 1

    async def _room(self, name: str | None) -> UUID | None:
        if name is None or not name.strip():
            return None
        return (await ensure_room_in(self._uow, name, self._now)).id

    # - - - Subjects - - -

    async def _subject(self, item: EmisTimetableItem) -> Subject:
        key = (item.subject_emis_id, item.subject_name.strip().casefold())
        subject = self._subjects.get(key)
        if subject is None:
            subject = await self._find_subject(item) or await self._new_subject(item)
            self._subjects[key] = subject
        if item.subgroup is not None and not subject.can_be_divided:
            subject.can_be_divided = True
            await self._uow.subjects.save(subject)
        return subject

    async def _find_subject(self, item: EmisTimetableItem) -> Subject | None:
        if item.subject_emis_id is not None:
            found = await self._uow.subjects.get_by_emis_id(item.subject_emis_id)
            if found is not None:
                return found
        wanted = item.subject_name.strip().casefold()
        for subject in await self._uow.subjects.search(item.subject_name.strip()):
            same_name = wanted in {n.strip().casefold() for n in subject.name.values()}
            if same_name and subject.emis_subject_id in (None, item.subject_emis_id):
                await self._adopt(subject, item.subject_emis_id)
                return subject
        return None

    async def _adopt(self, subject: Subject, emis_subject_id: int | None) -> None:
        if subject.emis_subject_id is None and emis_subject_id is not None:
            subject.emis_subject_id = emis_subject_id
            await self._uow.subjects.save(subject)

    async def _new_subject(self, item: EmisTimetableItem) -> Subject:
        name = item.subject_name.strip() or f"Subject {item.subject_emis_id}"
        subject = Subject(
            id=new_id(),
            name=dict.fromkeys(LANGUAGES, name),
            emis_subject_id=item.subject_emis_id,
        )
        await self._uow.subjects.add(subject)
        return subject


def _slot(entry: TimetableEntry) -> str:
    return f"{entry.weekday}/{entry.period}/{entry.week_parity}"


def _describe(item: EmisTimetableItem) -> str:
    return f"{item.weekday}/{item.pair_number}/{item.subject_name}"
