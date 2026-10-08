"""Create a timetable entry after checking conflicts (UF-ADM-06, ACA-8)."""

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
from app.modules.academic.application.schedule.results import TimetableEntryData
from app.shared.actor import Actor
from app.shared.clock import Clock
from app.shared.contracts.identity import IdentityDirectory
from app.shared.tasks import TaskKicker


class CreateEntry:
    """Add an entry to a term; conflicts block saving."""

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

    async def execute(self, actor: Actor, data: EntryInput) -> TimetableEntryData:
        """Insert the entry under the term's lock and regenerate lessons."""
        locale = await caller_locale(self.identity, actor)
        async with self.uow_factory() as uow:
            await uow.lock_term(data.term_id)
            entry = await build_entry(uow, data, now=self.clock.now(), create_room=True)
            raise_if_conflicts(await conflicts_for(uow, entry))
            await uow.entries.add(entry)
            kick_generation(uow, self.kicker, self.clock, entry.term_id)
            views = await build_entry_data(uow, self.identity, [entry], locale)
            await uow.commit()
        return views[0]
