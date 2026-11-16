"""Ports of the chooser slice: catalog reads and the student's list."""

from typing import Protocol
from uuid import UUID

from app.modules.admission.domain.chooser import (
    AffordabilityCheck,
    CatalogInstitution,
    CatalogScholarship,
    ListEntry,
)


class CatalogRepository(Protocol):
    """Published and provisional institutions with their facts."""

    async def institutions(
        self, *, country: str | None = None
    ) -> list[CatalogInstitution]:
        """Return non-archived institutions ordered by name."""
        ...

    async def institution(self, institution_id: UUID) -> CatalogInstitution | None:
        """Return one non-archived institution."""
        ...

    async def scholarships(
        self,
        *,
        institution_id: UUID | None = None,
        country: str | None = None,
        basis: str | None = None,
        coverage_min: int | None = None,
    ) -> list[CatalogScholarship]:
        """Return the institution's and the national scholarships, by name."""
        ...


class ListRepository(Protocol):
    """List entries, their affordability checks and the stated budget."""

    async def entries(self, student_id: UUID) -> list[ListEntry]:
        """Return a student's entries, oldest first."""
        ...

    async def entry(self, entry_id: UUID) -> ListEntry | None:
        """Return one entry."""
        ...

    async def find(self, student_id: UUID, institution_id: UUID) -> ListEntry | None:
        """Return the entry of an institution on a student's list."""
        ...

    async def add(self, entry: ListEntry) -> ListEntry:
        """Insert an entry."""
        ...

    async def save(self, entry: ListEntry, *, expected_lock: int) -> ListEntry:
        """Write an entry; `AdmissionConflictError` if `lock_version` moved."""
        ...

    async def delete(self, entry_id: UUID) -> None:
        """Remove an entry."""
        ...

    async def budget_band(self, student_id: UUID) -> str | None:
        """Return the student's stated yearly budget band."""
        ...

    async def affordability(self, entry_id: UUID) -> AffordabilityCheck | None:
        """Return the affordability check of an entry."""
        ...

    async def save_affordability(self, check: AffordabilityCheck) -> None:
        """Insert or replace the check of an entry."""
        ...
