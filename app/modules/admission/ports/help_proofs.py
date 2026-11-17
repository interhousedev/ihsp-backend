"""Port: storage of the proofs of items."""

from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.modules.admission.domain.help_proofs import Proof, ProofKind, ProofStatus


class ProofRepository(Protocol):
    """Proofs of items."""

    async def item_owner(self, item_id: UUID) -> UUID | None:
        """Return the student owning the item, or None."""
        ...

    async def add_proof(
        self,
        item_id: UUID,
        kind: ProofKind,
        *,
        url: str | None,
        file_id: UUID | None,
        text_sha256: str | None,
    ) -> Proof:
        """Insert a pending proof."""
        ...

    async def get_proof(self, proof_id: UUID) -> Proof | None:
        """Return one proof."""
        ...

    async def list_proofs(self, item_id: UUID) -> list[Proof]:
        """Return the item's proofs, oldest first."""
        ...

    async def set_proof_result(
        self,
        proof_id: UUID,
        *,
        status: ProofStatus,
        fetched_at: datetime,
        text_sha256: str | None,
        extraction: str | None,
    ) -> Proof:
        """Record a verification result."""
        ...


class HelpProofsRepository(ProofRepository, Protocol):
    """The proof repository, reached as `uow.help_proofs`."""


__all__ = ["HelpProofsRepository", "ProofRepository"]
