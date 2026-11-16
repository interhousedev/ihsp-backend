"""Port: staff catalog proposals and applying an approved one."""

from typing import Protocol
from uuid import UUID

from app.modules.admission.domain.catalog_proposals import CatalogProposal


class CatalogProposalRepository(Protocol):
    """Proposals, and the write of an approved one into the catalog."""

    async def add(self, proposal: CatalogProposal) -> CatalogProposal:
        """Insert a pending proposal."""
        ...

    async def get(self, proposal_id: UUID) -> CatalogProposal | None:
        """Return one proposal."""
        ...

    async def list(
        self, *, status: str | None = None, proposed_by: UUID | None = None
    ) -> list[CatalogProposal]:
        """Return proposals, newest first."""
        ...

    async def target_exists(self, kind: str, target_id: UUID) -> bool:
        """Return whether the institution or scholarship to edit exists."""
        ...

    async def apply(self, proposal: CatalogProposal) -> UUID:
        """Create or update the catalog row, publish it, return its id."""
        ...

    async def save_review(
        self, proposal: CatalogProposal, *, expected_lock: int
    ) -> CatalogProposal:
        """Write the review; `AdmissionConflictError` if `lock_version` moved."""
        ...
