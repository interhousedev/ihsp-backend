"""Port: keep the term's bells equal to EMIS (implemented by the schedule)."""

from typing import Protocol
from uuid import UUID


class BellSync(Protocol):
    """Reads the EMIS class hours through a student's link and stores them."""

    async def execute(self, user_id: UUID) -> object:
        """Apply the bells; raise EmisAuthFailed or EmisUnavailable on EMIS errors."""
        ...
