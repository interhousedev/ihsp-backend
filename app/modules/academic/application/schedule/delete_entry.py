"""Delete a timetable entry and tidy its future lessons (UF-ADM-06)."""

from uuid import UUID

from app.modules.academic.application.schedule.common import (
    UowFactory,
    kick_generation,
    kick_recompute_due_dates,
)
from app.modules.academic.application.schedule.ports.room_page_cache import (
    RoomPageCache,
)
from app.modules.academic.application.schedule.room_cache import (
    invalidate_room_pages,
)
from app.modules.academic.domain.schedule.errors import EntryNotFoundError
from app.shared.clock import Clock
from app.shared.tasks import TaskKicker


class DeleteEntry:
    """Remove an entry: empty future lessons go, lessons with content are cancelled."""

    def __init__(
        self,
        uow_factory: UowFactory,
        clock: Clock,
        kicker: TaskKicker,
        cache: RoomPageCache,
    ) -> None:
        """Store the dependencies."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.kicker = kicker
        self.cache = cache

    async def execute(self, entry_id: UUID) -> None:
        """Delete the entry; past and hand-changed lessons stay without it."""
        async with self.uow_factory() as uow:
            entry = await uow.entries.get(entry_id)
            if entry is None:
                raise EntryNotFoundError()
            await uow.lock_term(entry.term_id)
            changed = await uow.lessons.detach_entry(entry.id, self.clock.now())
            await uow.entries.delete(entry.id)
            kick_recompute_due_dates(uow, self.kicker, changed)
            kick_generation(uow, self.kicker, self.clock, entry.term_id)
            await invalidate_room_pages(uow, self.cache, [entry.room_id])
            await uow.commit()
