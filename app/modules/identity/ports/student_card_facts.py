"""Where the student card stores the EMIS facts it read.

The academic module owns these facts.
"""

from typing import Protocol
from uuid import UUID

from app.shared.contracts.emis import EmisProfile


class StudentCardFacts(Protocol):
    """Persist what EMIS says about the student's group (name, course, direction...)."""

    async def record_user_emis_facts(
        self, *, user_id: UUID, profile: EmisProfile
    ) -> None:
        """Store the facts for the group the student belongs to; no-op if none."""
        ...
