"""Find the current term: containing today, else the next, else the last."""

import datetime as dt

from app.modules.academic.application.schedule.common import UowFactory, today
from app.modules.academic.application.schedule.results import TermData
from app.modules.academic.application.schedule.term_views import term_data
from app.modules.academic.domain.schedule.term import pick_current_term
from app.shared.clock import Clock


class CurrentTerm:
    """Return the term that applies on a day."""

    def __init__(self, uow_factory: UowFactory, clock: Clock) -> None:
        """Store the dependencies."""
        self.uow_factory = uow_factory
        self.clock = clock

    async def execute(self, day: dt.date | None = None) -> TermData | None:
        """Return the term containing the day (default today), the next, or the last."""
        async with self.uow_factory() as uow:
            terms = await uow.terms.list_all()
        term = pick_current_term(terms, day or today(self.clock))
        return term_data(term, is_current=True) if term else None
