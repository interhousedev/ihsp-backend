"""Copy last term's timetable into a new term (ADM-9, UF-ADM-06 step 4)."""

from uuid import UUID

from app.modules.academic.application.schedule.common import (
    UowFactory,
    kick_generation,
)
from app.modules.academic.domain.schedule.conflicts import entry_conflicts
from app.modules.academic.domain.schedule.errors import (
    EntryInvalidError,
    TermNotFoundError,
)
from app.modules.academic.domain.schedule.timetable_entry import TimetableEntry
from app.shared.clock import Clock
from app.shared.ids import new_id
from app.shared.tasks import TaskKicker


class CopyTimetable:
    """Copy the open-ended entries of one term into another."""

    def __init__(
        self, uow_factory: UowFactory, clock: Clock, kicker: TaskKicker
    ) -> None:
        """Store the dependencies."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.kicker = kicker

    async def execute(self, from_term_id: UUID, to_term_id: UUID) -> int:
        """Copy entries valid until the end of the source term; return how many.

        Entries that end earlier were replaced by later ones and are not copied.
        Copies that would conflict with entries already in the target are skipped.
        """
        if from_term_id == to_term_id:
            raise EntryInvalidError(params={"reason": "same-term"})
        async with self.uow_factory() as uow:
            source = await uow.terms.get(from_term_id)
            target = await uow.terms.get(to_term_id)
            if source is None or target is None:
                raise TermNotFoundError()
            await uow.lock_term(target.id)
            created = 0
            for entry in await uow.entries.list_for_term(source.id):
                if entry.valid_to is not None:
                    continue
                copy = TimetableEntry(
                    id=new_id(),
                    term_id=target.id,
                    weekday=entry.weekday,
                    period=entry.period,
                    week_parity=entry.week_parity,
                    subject_id=entry.subject_id,
                    teacher_id=entry.teacher_id,
                    room_id=entry.room_id,
                    audience=list(entry.audience),
                    valid_from=target.starts_on,
                    valid_to=None,
                )
                others = await uow.entries.same_slot(
                    target.id, copy.weekday, copy.period
                )
                if entry_conflicts(copy, others):
                    continue
                await uow.entries.add(copy)
                created += 1
            if created:
                kick_generation(uow, self.kicker, self.clock, target.id)
            await uow.commit()
        return created
