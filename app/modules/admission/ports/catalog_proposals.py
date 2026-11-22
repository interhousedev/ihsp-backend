"""Port: staff catalog proposals and applying an approved one."""

import datetime as dt
from collections.abc import Mapping, Sequence
from typing import Any, Literal, Protocol
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

    async def set_logo(
        self, institution_id: UUID, *, zoom: float | None, fit: str | None
    ) -> bool:
        """Set the given logo fields of a published institution; False: unknown."""
        ...

    async def lock_submissions(self) -> None:
        """Serialise institution submissions until the transaction ends.

        Take it before `find_duplicate` so the lookup and the insert are atomic.
        """
        ...

    async def find_duplicate(
        self, names: Sequence[str], website_domain: str | None
    ) -> tuple[Literal["institution", "proposal"], UUID] | None:
        """Find an institution or a pending create proposal that equals the input.

        `names` are NFC-casefolded; an institution matches by name, alias or
        domain, a pending create proposal by name, alias or domain.
        """
        ...

    async def apply(
        self, proposal: CatalogProposal, *, reviewer_id: UUID, now: dt.datetime
    ) -> UUID:
        """Create or update the catalog row and its facts, publish, return its id."""
        ...

    async def apply_facts(
        self,
        institution_id: UUID,
        facts: Mapping[str, Mapping[str, Any]],
        reviewer_id: UUID,
        now: dt.datetime,
    ) -> None:
        """Upsert sourced facts `{key: {value, source_url, year, note}}` in place."""
        ...

    async def save_review(
        self, proposal: CatalogProposal, *, expected_lock: int
    ) -> CatalogProposal:
        """Write the review; `AdmissionConflictError` if `lock_version` moved."""
        ...
