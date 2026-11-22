"""Port: facts, scholarships and description of one institution, for curators."""

import datetime as dt
from typing import Any, Protocol
from uuid import UUID

from app.modules.admission.domain.catalog_card import CardFact
from app.modules.admission.domain.chooser import CatalogScholarship


class CatalogCardRepository(Protocol):
    """Curator reads and writes beside the institution row."""

    async def facts(self, institution_id: UUID) -> list[CardFact]:
        """Published facts of the institution."""
        ...

    async def set_verified(
        self, institution_id: UUID, key: str, reviewer_id: UUID | None
    ) -> None:
        """Mark a published fact reviewed (a reviewer) or not (None)."""
        ...

    async def delete_fact(self, institution_id: UUID, key: str) -> bool:
        """Remove every row of a fact key; False when there was none."""
        ...

    async def description(self, institution_id: UUID) -> dict[str, str] | None:
        """The description per locale."""
        ...

    async def set_description(
        self, institution_id: UUID, value: dict[str, str] | None, now: dt.datetime
    ) -> None:
        """Replace the description."""
        ...

    async def scholarships(self, institution_id: UUID) -> list[CatalogScholarship]:
        """Scholarships of the institution, any status."""
        ...

    async def create_scholarship(
        self, institution_id: UUID, values: dict[str, Any]
    ) -> UUID:
        """Insert a published scholarship; return its id."""
        ...

    async def update_scholarship(
        self, institution_id: UUID, scholarship_id: UUID, values: dict[str, Any]
    ) -> bool:
        """Overwrite columns; False when it is not this institution's."""
        ...

    async def delete_scholarship(
        self, institution_id: UUID, scholarship_id: UUID
    ) -> bool:
        """Remove a scholarship; False when it is not this institution's."""
        ...
