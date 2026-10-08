"""Check an entry for conflicts without saving it (UF-ADM-06 step 3)."""

from uuid import UUID

from app.modules.academic.application.schedule.common import UowFactory
from app.modules.academic.application.schedule.entry_builder import (
    EntryInput,
    build_entry,
    conflicts_for,
)
from app.modules.academic.application.schedule.results import ConflictData
from app.shared.clock import Clock


class CheckEntry:
    """Report the conflicts an entry would have; nothing is written."""

    def __init__(self, uow_factory: UowFactory, clock: Clock) -> None:
        """Store the dependencies."""
        self.uow_factory = uow_factory
        self.clock = clock

    async def execute(
        self, data: EntryInput, *, entry_id: UUID | None = None
    ) -> list[ConflictData]:
        """Return the conflicts; pass entry_id to ignore the entry being edited."""
        async with self.uow_factory() as uow:
            entry = await build_entry(
                uow, data, now=self.clock.now(), create_room=False, entry_id=entry_id
            )
            conflicts = await conflicts_for(uow, entry)
        return [
            ConflictData(c.kind, c.with_entry_id, c.with_lesson_id, c.description)
            for c in conflicts
        ]
