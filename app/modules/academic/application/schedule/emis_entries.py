"""Keep a group's EMIS-sourced timetable entries equal to EMIS (ACA-1, ACA-5).

Only entries whose ``source`` is "emis" are touched; entries Administration made or
edited by hand are other people's work and only count as clashes. A student sees only
their own half of a class taught in halves, so one run answers for the whole-group
slots and the slots of the halves it saw (``scope``), never for the other half's.
"""

import datetime as dt
from collections.abc import Collection, Sequence
from dataclasses import dataclass, field, replace
from uuid import UUID

from app.modules.academic.application.schedule.bootstrap_teachers import (
    TeacherResolver,
)
from app.modules.academic.application.schedule.emis_subjects import SubjectResolver
from app.modules.academic.application.schedule.ensure_room import ensure_room_in
from app.modules.academic.application.schedule.ports.unit_of_work import (
    ScheduleUnitOfWork,
)
from app.modules.academic.domain import audience as audience_keys
from app.modules.academic.domain.schedule.conflicts import entry_conflicts
from app.modules.academic.domain.schedule.emis_timetable import DerivedSlot
from app.modules.academic.domain.schedule.entry_merge import merge_target
from app.modules.academic.domain.schedule.group import Group
from app.modules.academic.domain.schedule.term import Term
from app.modules.academic.domain.schedule.timetable_entry import (
    TimetableEntry,
    WeekParity,
    validate_entry,
)
from app.shared.ids import new_id

import structlog

log = structlog.get_logger(__name__)

MAX_PERIOD = 20
Identity = tuple[
    int, int, WeekParity, UUID, str
]  # weekday, period, parity, subject, key


@dataclass(slots=True)
class EntryTally:
    """What a reconciliation did with the entries."""

    added: int = 0
    merged: int = 0
    updated: int = 0
    removed: int = 0
    skipped: int = 0
    changed_lessons: list[UUID] = field(default_factory=list)
    room_ids: set[UUID | None] = field(default_factory=set)


@dataclass(frozen=True, slots=True)
class Wanted:
    """A slot EMIS shows, with its subject, teacher and room resolved."""

    identity: Identity
    key: str
    teacher_id: UUID | None
    room_id: UUID | None


class EntryReconciler:
    """Adds, updates and removes the EMIS entries of one group inside a transaction."""

    def __init__(
        self,
        uow: ScheduleUnitOfWork,
        *,
        term: Term,
        group: Group,
        teachers: TeacherResolver,
        subjects: SubjectResolver,
        now: dt.datetime,
    ) -> None:
        """Bind to the transaction, the term, the group and the resolvers."""
        self._uow = uow
        self._term = term
        self._group = group
        self._teachers = teachers
        self._subjects = subjects
        self._now = now
        self._tally = EntryTally()

    async def run(
        self, slots: Sequence[DerivedSlot], scope: Collection[int | None]
    ) -> EntryTally:
        """Make the group's EMIS entries in ``scope`` equal to ``slots``."""
        keys = {audience_keys.key(self._group.id, half) for half in scope}
        wanted = await self._wanted(slots)
        stored = await self._stored(keys)
        for identity, (entry, key) in stored.items():
            if identity not in wanted:
                await self._detach(entry, key)
                self._tally.removed += 1
        to_add: list[Wanted] = []
        for identity, want in wanted.items():
            found = stored.get(identity)
            if found is None:
                to_add.append(want)
            elif (found[0].teacher_id, found[0].room_id) != (
                want.teacher_id,
                want.room_id,
            ) and await self._update(found[0], found[1], want):
                to_add.append(want)
        for want in to_add:
            await self._add(want)
        return self._tally

    async def _wanted(self, slots: Sequence[DerivedSlot]) -> dict[Identity, Wanted]:
        wanted: dict[Identity, Wanted] = {}
        for slot in slots:
            if not 1 <= slot.period <= MAX_PERIOD:
                self._tally.skipped += 1
                continue
            item = slot.latest
            subject = await self._subjects.resolve(
                item.subject, divided=slot.subgroup is not None
            )
            key = audience_keys.key(self._group.id, slot.subgroup)
            identity: Identity = (
                slot.weekday,
                slot.period,
                slot.parity,
                subject.id,
                key,
            )
            if identity in wanted:  # two teachers for one slot: the first wins
                self._tally.skipped += 1
                continue
            wanted[identity] = Wanted(
                identity,
                key,
                await self._teachers.resolve(item.teacher),
                await self._room(item.room),
            )
        return wanted

    async def _stored(
        self, keys: set[str]
    ) -> dict[Identity, tuple[TimetableEntry, str]]:
        stored: dict[Identity, tuple[TimetableEntry, str]] = {}
        for entry in await self._uow.entries.list_for_term(self._term.id):
            if entry.source != "emis":
                continue
            for key in entry.audience:
                if key in keys:
                    identity = (
                        entry.weekday,
                        entry.period,
                        entry.week_parity,
                        entry.subject_id,
                        key,
                    )
                    stored[identity] = (entry, key)
        return stored

    async def _room(self, name: str | None) -> UUID | None:
        if name is None or not name.strip():
            return None
        return (await ensure_room_in(self._uow, name, self._now)).id

    async def _detach(self, entry: TimetableEntry, key: str) -> None:
        """Take the group's key off an entry; an entry nobody attends is deleted."""
        self._tally.room_ids.add(entry.room_id)
        remaining = [k for k in entry.audience if k != key]
        if remaining:
            entry.audience = remaining
            await self._uow.entries.save(entry)
            return
        changed = await self._uow.lessons.detach_entry(entry.id, self._now)
        self._tally.changed_lessons.extend(changed)
        await self._uow.entries.delete(entry.id)

    async def _update(self, entry: TimetableEntry, key: str, want: Wanted) -> bool:
        """Change teacher and room in place; True if the slot must be added anew.

        An entry shared with other groups is not changed under them: the group
        leaves it and gets an entry of its own (or joins a matching one).
        """
        if entry.audience != [key]:
            await self._detach(entry, key)
            return True
        candidate = replace(entry, teacher_id=want.teacher_id, room_id=want.room_id)
        others = await self._uow.entries.same_slot(
            entry.term_id, entry.weekday, entry.period
        )
        if entry_conflicts(candidate, others):
            log.warning("emis_entry_update_skipped", slot=_slot(entry))
            self._tally.skipped += 1
            return False
        self._tally.room_ids.update((entry.room_id, want.room_id))
        entry.teacher_id, entry.room_id = want.teacher_id, want.room_id
        await self._uow.entries.save(entry)
        self._tally.updated += 1
        return False

    async def _add(self, want: Wanted) -> None:
        weekday, period, parity, subject_id, _ = want.identity
        entry = TimetableEntry(
            id=new_id(),
            term_id=self._term.id,
            weekday=weekday,
            period=period,
            week_parity=parity,
            subject_id=subject_id,
            teacher_id=want.teacher_id,
            room_id=want.room_id,
            audience=[want.key],
            valid_from=self._term.starts_on,
            source="emis",
        )
        validate_entry(entry)
        self._tally.room_ids.add(want.room_id)
        others = await self._uow.entries.same_slot(entry.term_id, weekday, period)
        if not entry_conflicts(entry, others):
            await self._uow.entries.add(entry)
            self._tally.added += 1
            return
        target = merge_target(entry, others)
        if target is None or target.source != "emis":
            log.warning("emis_entry_skipped", reason="conflict", slot=_slot(entry))
            self._tally.skipped += 1
            return
        target.audience = [*target.audience, *entry.audience]
        await self._uow.entries.save(target)
        self._tally.merged += 1


def _slot(entry: TimetableEntry) -> str:
    return f"{entry.weekday}/{entry.period}/{entry.week_parity}"
