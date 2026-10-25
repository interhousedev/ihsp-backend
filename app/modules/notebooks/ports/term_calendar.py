"""Port: the dates of the current study term (answered by the academic schedule)."""

from datetime import date
from typing import Protocol


class TermCalendar(Protocol):
    """Which dates "this term" covers."""

    async def current_term_dates(self, today: date) -> tuple[date, date] | None:
        """First and last day of the term that holds `today` (else the next one).

        None when the calendar has no term at all.
        """
        ...
