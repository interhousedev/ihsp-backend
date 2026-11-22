"""Port: stored country facts."""

from typing import Any, Protocol
from uuid import UUID

from app.modules.admission.domain.country_facts import CountryFacts


class CountryFactsRepository(Protocol):
    """Reads and writes the facts of countries."""

    async def get_many(self, codes: list[str]) -> list[CountryFacts]:
        """The stored rows of the codes (a country without a row is absent)."""
        ...

    async def list_all(self) -> list[CountryFacts]:
        """Every stored row."""
        ...

    async def save(
        self,
        country: str,
        *,
        as_of: str,
        facts: dict[str, dict[str, Any]],
        editor: UUID,
        verified: bool,
    ) -> CountryFacts:
        """Replace the facts as a staff edit (the seed never overwrites such a row)."""
        ...

    async def set_verified(self, country: str, editor: UUID) -> CountryFacts | None:
        """Mark a stored row verified; None when the country has no row."""
        ...
