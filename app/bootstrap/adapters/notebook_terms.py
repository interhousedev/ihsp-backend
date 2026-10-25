"""TermCalendar for the notebooks module, answered by the academic schedule."""

import datetime as dt

from app.modules.academic.application.schedule.current_term import CurrentTerm


class NotebookTermsAdapter:
    """Notebooks ← academic: the dates of "this term" for subject notebooks."""

    def __init__(self, current_term: CurrentTerm) -> None:
        """Keep the schedule's current-term use case."""
        self._current_term = current_term

    async def current_term_dates(
        self, today: dt.date
    ) -> tuple[dt.date, dt.date] | None:
        """First and last day of the term holding today (else the next one)."""
        term = await self._current_term.execute(today)
        return (term.starts_on, term.ends_on) if term else None
