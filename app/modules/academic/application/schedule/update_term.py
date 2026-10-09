"""Change a term; future lessons get the new calendar (UF-ADM-05)."""

import datetime as dt
from collections.abc import Sequence
from uuid import UUID

from app.modules.academic.application.schedule.common import (
    UowFactory,
    kick_generation,
    today,
)
from app.modules.academic.application.schedule.results import TermData
from app.modules.academic.application.schedule.term_checks import check_term
from app.modules.academic.application.schedule.term_views import term_list
from app.modules.academic.domain.schedule.errors import TermNotFoundError
from app.modules.academic.domain.schedule.term import Bell, ControlPeriods, MovedDay
from app.shared.clock import Clock
from app.shared.tasks import TaskKicker


class UpdateTerm:
    """Apply a partial change to a term and regenerate its lessons."""

    def __init__(
        self, uow_factory: UowFactory, clock: Clock, kicker: TaskKicker
    ) -> None:
        """Store the dependencies."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.kicker = kicker

    async def execute(
        self,
        term_id: UUID,
        *,
        academic_year: str | None = None,
        half: int | None = None,
        starts_on: dt.date | None = None,
        ends_on: dt.date | None = None,
        bells: Sequence[Bell] | None = None,
        non_study_days: Sequence[dt.date] | None = None,
        moved_days: Sequence[MovedDay] | None = None,
        control_periods: ControlPeriods | None = None,
    ) -> TermData:
        """Change the given fields; None means unchanged."""
        async with self.uow_factory() as uow:
            term = await uow.terms.get(term_id)
            if term is None:
                raise TermNotFoundError()
            if academic_year is not None:
                term.academic_year = academic_year.strip()
            term.half = half if half is not None else term.half
            term.starts_on = starts_on or term.starts_on
            term.ends_on = ends_on or term.ends_on
            if bells is not None:
                term.bells = sorted(bells, key=lambda bell: bell.period)
            if non_study_days is not None:
                term.non_study_days = sorted(set(non_study_days))
            if moved_days is not None:
                term.moved_days = list(moved_days)
            if control_periods is not None:
                term.control_periods = control_periods
            await check_term(uow, term, exclude_id=term.id)
            await uow.terms.save(term)
            kick_generation(uow, self.kicker, self.clock, term.id)
            current = term_list(await uow.terms.list_all(), today(self.clock))
            await uow.commit()
        return next(item for item in current if item.id == term_id)
