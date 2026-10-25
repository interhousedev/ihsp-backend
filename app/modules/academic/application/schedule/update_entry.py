"""Change a timetable entry; future generated lessons follow (UF-ADM-06 5a)."""

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from app.modules.academic.application.schedule.common import (
    UowFactory,
    caller_locale,
    kick_generation,
)
from app.modules.academic.application.schedule.entry_builder import (
    EntryInput,
    build_entry,
    conflicts_for,
    raise_if_conflicts,
)
from app.modules.academic.application.schedule.entry_views import build_entry_data
from app.modules.academic.application.schedule.ports.unit_of_work import (
    ScheduleUnitOfWork,
)
from app.modules.academic.application.schedule.results import TimetableEntryData
from app.modules.academic.application.schedule.unset import UNSET, Unset
from app.modules.academic.domain import audience as audience_keys
from app.modules.academic.domain.schedule.errors import EntryNotFoundError
from app.modules.academic.domain.schedule.timetable_entry import (
    TimetableEntry,
    WeekParity,
)
from app.shared.actor import Actor
from app.shared.clock import Clock
from app.shared.contracts.identity import IdentityDirectory
from app.shared.tasks import TaskKicker


@dataclass(frozen=True, slots=True)
class EntryPatch:
    """A partial change; UNSET means "keep", None clears nullable fields."""

    term_id: UUID | None = None
    weekday: int | None = None
    period: int | None = None
    week_parity: WeekParity | None = None
    subject_id: UUID | None = None
    teacher_id: UUID | None | Unset = UNSET
    room_name: str | None | Unset = UNSET
    audience: Sequence[tuple[UUID, int | None]] | None = None
    valid_from: dt.date | None = None
    valid_to: dt.date | None | Unset = UNSET


class UpdateEntry:
    """Apply a patch to an entry and re-check conflicts."""

    def __init__(
        self,
        uow_factory: UowFactory,
        identity: IdentityDirectory,
        clock: Clock,
        kicker: TaskKicker,
    ) -> None:
        """Store the dependencies."""
        self.uow_factory = uow_factory
        self.identity = identity
        self.clock = clock
        self.kicker = kicker

    async def execute(
        self, actor: Actor, entry_id: UUID, patch: EntryPatch
    ) -> TimetableEntryData:
        """Save the changed entry unless it conflicts with another one."""
        locale = await caller_locale(self.identity, actor)
        async with self.uow_factory() as uow:
            current = await uow.entries.get(entry_id)
            if current is None:
                raise EntryNotFoundError()
            data = await self._merge(uow, current, patch)
            await uow.lock_term(data.term_id)
            entry = await build_entry(
                uow,
                data,
                now=self.clock.now(),
                create_room=True,
                entry_id=entry_id,
            )
            raise_if_conflicts(await conflicts_for(uow, entry))
            old_term_id = current.term_id
            await uow.entries.save(entry)
            kick_generation(uow, self.kicker, self.clock, entry.term_id)
            if old_term_id != entry.term_id:
                kick_generation(uow, self.kicker, self.clock, old_term_id)
            views = await build_entry_data(uow, self.identity, [entry], locale)
            await uow.commit()
        return views[0]

    @staticmethod
    async def _merge(
        uow: ScheduleUnitOfWork, current: TimetableEntry, patch: EntryPatch
    ) -> EntryInput:
        if isinstance(patch.room_name, Unset):
            room = await uow.rooms.get(current.room_id) if current.room_id else None
            room_name = room.name if room else None
        else:
            room_name = patch.room_name
        return EntryInput(
            term_id=patch.term_id or current.term_id,
            weekday=patch.weekday or current.weekday,
            period=patch.period or current.period,
            week_parity=patch.week_parity or current.week_parity,
            subject_id=patch.subject_id or current.subject_id,
            teacher_id=(
                current.teacher_id
                if isinstance(patch.teacher_id, Unset)
                else patch.teacher_id
            ),
            room_name=room_name,
            audience=(
                patch.audience
                if patch.audience is not None
                else [audience_keys.parse(key) for key in current.audience]
            ),
            valid_from=patch.valid_from or current.valid_from,
            valid_to=(
                current.valid_to
                if isinstance(patch.valid_to, Unset)
                else patch.valid_to
            ),
        )
