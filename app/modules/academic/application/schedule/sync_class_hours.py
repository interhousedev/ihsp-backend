"""Keep the current term's bells equal to the EMIS class hours (ACA-4)."""

import datetime as dt
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from app.modules.academic.application.schedule.common import UowFactory, today
from app.modules.academic.application.schedule.generate_lessons import (
    DEFAULT_DAYS,
    GenerateLessons,
)
from app.modules.academic.domain.schedule.emis_bells import (
    bells_from_class_hours,
    merge_emis_bells,
)
from app.modules.academic.domain.schedule.term import pick_current_term
from app.shared.clock import Clock
from app.shared.contracts.emis import EmisClassHour, EmisSource

import structlog

log = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ClassHoursResult:
    """What a bell sync did: ``changed`` also regenerated future lessons."""

    status: Literal["changed", "unchanged", "no_term", "empty"]
    term_id: UUID | None = None
    lessons_changed: int = 0


class SyncClassHours:
    """Fetch the EMIS bells and store them in the current term, only if they differ."""

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        emis: EmisSource,
        generate: GenerateLessons,
        clock: Clock,
    ) -> None:
        """Store the dependencies."""
        self.uow_factory = uow_factory
        self.emis = emis
        self.generate = generate
        self.clock = clock

    async def execute(self, user_id: UUID) -> ClassHoursResult:
        """Read the bells through the student's EMIS link and apply them.

        Raises EmisAuthFailed or EmisUnavailable when EMIS cannot be read.
        """
        return await self.apply(await self.emis.class_hours(user_id))

    async def apply(self, hours: list[EmisClassHour]) -> ClassHoursResult:
        """Store the bells; when they changed, future lessons get the new times."""
        from_emis = bells_from_class_hours(hours)
        if not from_emis:
            return ClassHoursResult("empty")  # never wipe the bells on an empty answer
        async with self.uow_factory() as uow:
            term = pick_current_term(await uow.terms.list_all(), today(self.clock))
            if term is None:
                return ClassHoursResult("no_term")
            merged = merge_emis_bells(term.bells, from_emis)
            if merged is None:
                return ClassHoursResult("unchanged", term.id)
            term.bells = merged
            await uow.terms.save(term)
            await uow.commit()
        log.info("emis_bells_changed", term_id=str(term.id), periods=len(merged))
        changed = await self._regenerate(term.id, term.starts_on, term.ends_on)
        return ClassHoursResult("changed", term.id, changed)

    async def _regenerate(
        self, term_id: UUID, starts_on: dt.date, ends_on: dt.date
    ) -> int:
        """Regenerate the lessons that exist from today on; past ones stay.

        The window is the usual one (ACA-7: 14 days ahead) or, if lessons were
        generated further ahead, up to the last of them, so a bell change moves
        every generated future lesson without generating new ones far ahead.
        Generation itself skips lessons that already started and lessons changed
        by hand.
        """
        start = max(today(self.clock), starts_on)
        async with self.uow_factory() as uow:
            generated = await uow.lessons.generated_in_range(term_id, start, ends_on)
        last = max((lesson.date for lesson in generated), default=start)
        days = max((last - start).days + 1, DEFAULT_DAYS)
        return await self.generate.execute(term_id=term_id, from_date=start, days=days)
