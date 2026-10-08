"""List timetable entries of a term for a group, teacher or room (ADM-9)."""

from uuid import UUID

from app.modules.academic.application.schedule.common import (
    UowFactory,
    caller_locale,
    today,
)
from app.modules.academic.application.schedule.entry_views import build_entry_data
from app.modules.academic.application.schedule.results import TimetableEntryData
from app.modules.academic.domain.schedule.term import pick_current_term
from app.shared.actor import Actor
from app.shared.clock import Clock
from app.shared.contracts.identity import IdentityDirectory


class ListEntries:
    """Return the entries of a term, defaulting to the current term."""

    def __init__(
        self, uow_factory: UowFactory, identity: IdentityDirectory, clock: Clock
    ) -> None:
        """Store the dependencies."""
        self.uow_factory = uow_factory
        self.identity = identity
        self.clock = clock

    async def execute(
        self,
        actor: Actor,
        *,
        term_id: UUID | None = None,
        group_id: UUID | None = None,
        teacher_id: UUID | None = None,
        room_id: UUID | None = None,
    ) -> list[TimetableEntryData]:
        """Return entries ordered by weekday and period."""
        locale = await caller_locale(self.identity, actor)
        async with self.uow_factory() as uow:
            if term_id is None:
                current = pick_current_term(
                    await uow.terms.list_all(), today(self.clock)
                )
                if current is None:
                    return []
                term_id = current.id
            entries = await uow.entries.search(
                term_id, group_id=group_id, teacher_id=teacher_id, room_id=room_id
            )
            entries.sort(key=lambda e: (e.weekday, e.period, e.week_parity))
            return await build_entry_data(uow, self.identity, entries, locale)
