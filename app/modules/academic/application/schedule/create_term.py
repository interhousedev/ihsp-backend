"""Create a term (ADM-8, ACA-4)."""

import datetime as dt
from collections.abc import Sequence

from app.modules.academic.application.schedule.common import UowFactory, today
from app.modules.academic.application.schedule.results import TermData
from app.modules.academic.application.schedule.term_checks import check_term
from app.modules.academic.application.schedule.term_views import term_list
from app.modules.academic.domain.schedule.term import (
    Bell,
    ControlPeriods,
    MovedDay,
    Term,
)
from app.shared.clock import Clock
from app.shared.ids import new_id


class CreateTerm:
    """Create a term after checking dates, bells and overlaps."""

    def __init__(self, uow_factory: UowFactory, clock: Clock) -> None:
        """Store the dependencies."""
        self.uow_factory = uow_factory
        self.clock = clock

    async def execute(
        self,
        *,
        academic_year: str,
        half: int,
        starts_on: dt.date,
        ends_on: dt.date,
        bells: Sequence[Bell],
        non_study_days: Sequence[dt.date],
        moved_days: Sequence[MovedDay],
        control_periods: ControlPeriods | None = None,
    ) -> TermData:
        """Validate and insert the term."""
        term = Term(
            id=new_id(),
            academic_year=academic_year.strip(),
            half=half,
            starts_on=starts_on,
            ends_on=ends_on,
            bells=sorted(bells, key=lambda bell: bell.period),
            non_study_days=sorted(set(non_study_days)),
            moved_days=list(moved_days),
            control_periods=control_periods or ControlPeriods(),
        )
        async with self.uow_factory() as uow:
            await check_term(uow, term, exclude_id=None)
            await uow.terms.add(term)
            current = term_list(await uow.terms.list_all(), today(self.clock))
            await uow.commit()
        return next(item for item in current if item.id == term.id)
