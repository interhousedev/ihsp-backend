"""List terms (ADM-8)."""

from app.modules.academic.application.schedule.common import UowFactory, today
from app.modules.academic.application.schedule.results import TermData
from app.modules.academic.application.schedule.term_views import term_list
from app.shared.clock import Clock


class ListTerms:
    """Return all terms ordered by start date."""

    def __init__(self, uow_factory: UowFactory, clock: Clock) -> None:
        """Store the dependencies."""
        self.uow_factory = uow_factory
        self.clock = clock

    async def execute(self) -> list[TermData]:
        """Return the terms with the current one flagged."""
        async with self.uow_factory() as uow:
            terms = await uow.terms.list_all()
        return term_list(terms, today(self.clock))
