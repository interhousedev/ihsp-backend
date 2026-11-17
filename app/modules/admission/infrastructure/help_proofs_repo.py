"""SQL repository of the proofs of items."""

from datetime import datetime
from typing import cast
from uuid import UUID

from app.modules.admission.domain.errors import AdmissionConflictError
from app.modules.admission.domain.help_proofs import Proof, ProofKind, ProofStatus
from app.modules.admission.infrastructure.orm.profile import ItemRow, ProofRow
from app.shared.ids import new_id

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


def _proof(row: ProofRow) -> Proof:
    return Proof(
        id=row.id,
        item_id=row.item_id,
        kind=cast(ProofKind, row.kind),
        status=cast(ProofStatus, row.status),
        url=row.url,
        file_id=row.file_id,
        text_sha256=row.text_sha256,
        extraction=row.extraction,
        fetched_at=row.fetched_at,
        next_check_at=row.next_check_at,
        lock_version=row.lock_version,
    )


class SqlHelpProofsRepository:
    """Proofs on one session."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the session."""
        self.session = session

    async def item_owner(self, item_id: UUID) -> UUID | None:
        """Return the student owning the item, or None."""
        owner: UUID | None = await self.session.scalar(
            select(ItemRow.student_id).where(ItemRow.id == item_id)
        )
        return owner

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
        row = ProofRow(
            id=new_id(),
            item_id=item_id,
            kind=kind,
            url=url,
            file_id=file_id,
            text_sha256=text_sha256,
            status="pending",
        )
        self.session.add(row)
        await self.session.flush()
        await self.session.refresh(row)
        return _proof(row)

    async def get_proof(self, proof_id: UUID) -> Proof | None:
        """Return one proof."""
        row = await self.session.get(ProofRow, proof_id)
        return _proof(row) if row else None

    async def list_proofs(self, item_id: UUID) -> list[Proof]:
        """Return the item's proofs, oldest first."""
        rows = await self.session.scalars(
            select(ProofRow).where(ProofRow.item_id == item_id).order_by(ProofRow.id)
        )
        return [_proof(r) for r in rows]

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
        row = await self.session.get(ProofRow, proof_id)
        if row is None:
            raise AdmissionConflictError()
        row.status = status
        row.fetched_at = fetched_at
        row.text_sha256 = text_sha256 or row.text_sha256
        row.extraction = extraction
        row.lock_version += 1
        await self.session.flush()
        return _proof(row)
