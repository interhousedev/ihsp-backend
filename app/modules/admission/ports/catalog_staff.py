"""Port: the staff tables of institutions and opportunities."""

from typing import Any, Protocol
from uuid import UUID

from app.modules.admission.domain.catalog_staff import (
    InstitutionPage,
    StaffInstitution,
)
from app.modules.admission.domain.opportunities import Opportunity


class CatalogStaffRepository(Protocol):
    """Searchable lists and hard deletes for the catalog curators."""

    async def search_opportunities(
        self,
        *,
        query: str | None,
        kind: str | None,
        archived: bool | None,
        offset: int,
        limit: int,
    ) -> tuple[list[Opportunity], int]:
        """One page of entries (live and archived) and the total of the filter."""
        ...

    async def opportunity_in_use(self, opportunity_id: UUID) -> bool:
        """Whether a student plan or an activity refers to the entry."""
        ...

    async def delete_opportunity(self, opportunity_id: UUID) -> None:
        """Remove an entry for good."""
        ...

    async def search_institutions(
        self,
        *,
        query: str | None,
        country: str | None,
        status: str | None,
        offset: int,
        limit: int,
    ) -> InstitutionPage:
        """One page of institutions, newest edit first."""
        ...

    async def get_institution(self, institution_id: UUID) -> StaffInstitution | None:
        """One institution of any status."""
        ...

    async def create_institution(self, values: dict[str, Any]) -> UUID:
        """Insert an institution; return its id."""
        ...

    async def update_institution(
        self, institution_id: UUID, values: dict[str, Any], *, expected_lock: int
    ) -> bool:
        """Overwrite the given columns; `AdmissionConflictError` if the lock moved.

        Returns False when the institution is unknown.
        """
        ...

    async def institution_in_use(self, institution_id: UUID) -> bool:
        """Whether student data (lists, essays, chats, outcomes) refers to it."""
        ...

    async def delete_institution(self, institution_id: UUID) -> None:
        """Remove an institution with its facts and catalog rows."""
        ...
