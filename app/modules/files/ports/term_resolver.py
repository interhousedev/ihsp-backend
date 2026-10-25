"""Terms of the academic module, as the files module needs them."""

from datetime import date
from typing import Protocol
from uuid import UUID


class TermResolver(Protocol):
    """Implemented by I1 over the academic module."""

    async def current_term_id(self, today: date) -> UUID | None:
        """Return the term containing today, else the next one, else None."""
        ...

    async def term_end(self, term_id: UUID) -> date | None:
        """Return the last day of the term, or None if the term is unknown."""
        ...
