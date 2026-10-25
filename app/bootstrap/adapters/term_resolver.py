"""TermResolver for the files module, answered by the academic schedule."""

import datetime as dt
from uuid import UUID

from app.modules.academic.application.schedule.current_term import CurrentTerm
from app.modules.academic.application.schedule.list_terms import ListTerms


class TermResolverAdapter:
    """Files ← academic: which term a student's file belongs to and when it ends."""

    def __init__(self, current_term: CurrentTerm, list_terms: ListTerms) -> None:
        """Keep the two schedule use cases."""
        self._current_term = current_term
        self._list_terms = list_terms

    async def current_term_id(self, today: dt.date) -> UUID | None:
        """Return the term containing today, else the next one, else None."""
        term = await self._current_term.execute(today)
        return term.id if term else None

    async def term_end(self, term_id: UUID) -> dt.date | None:
        """Return the last day of the term, or None if the term is unknown."""
        for term in await self._list_terms.execute():
            if term.id == term_id:
                return term.ends_on
        return None
