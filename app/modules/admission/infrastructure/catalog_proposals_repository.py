"""SQL repository of catalog proposals."""

from typing import Any
from uuid import UUID

from app.modules.admission.domain.catalog_proposals import CatalogProposal
from app.modules.admission.domain.errors import AdmissionConflictError
from app.modules.admission.infrastructure.orm.catalog import (
    CatalogProposalRow,
    InstitutionRow,
    ScholarshipRow,
    SourceRow,
)
from app.shared.ids import new_id

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

_TARGETS: dict[str, Any] = {
    "institution": InstitutionRow,
    "scholarship": ScholarshipRow,
}


def _proposal(r: CatalogProposalRow) -> CatalogProposal:
    return CatalogProposal(
        id=r.id,
        kind=r.kind,  # type: ignore[arg-type]
        target_id=r.target_id,
        payload=dict(r.payload),
        source_url=r.source_url,
        note=r.note,
        status=r.status,  # type: ignore[arg-type]
        proposed_by=r.proposed_by,
        created_at=r.created_at,
        lock_version=r.lock_version,
        reviewed_by=r.reviewed_by,
        reviewed_at=r.reviewed_at,
        review_note=r.review_note,
        applied_id=r.applied_id,
    )


class SqlCatalogProposalRepository:
    """Proposals and the write of an approved one into the catalog."""

    def __init__(self, session: AsyncSession) -> None:
        """Keep the session."""
        self._s = session

    async def add(self, proposal: CatalogProposal) -> CatalogProposal:
        """Insert a pending proposal."""
        row = CatalogProposalRow(
            id=proposal.id,
            kind=proposal.kind,
            target_id=proposal.target_id,
            payload=proposal.payload,
            source_url=proposal.source_url,
            note=proposal.note,
            status="pending",
            proposed_by=proposal.proposed_by,
        )
        self._s.add(row)
        await self._s.flush()
        await self._s.refresh(row)
        return _proposal(row)

    async def get(self, proposal_id: UUID) -> CatalogProposal | None:
        """Return one proposal."""
        row = await self._s.get(CatalogProposalRow, proposal_id)
        return _proposal(row) if row else None

    async def list(
        self, *, status: str | None = None, proposed_by: UUID | None = None
    ) -> list[CatalogProposal]:
        """Return proposals, newest first."""
        q = select(CatalogProposalRow).order_by(CatalogProposalRow.created_at.desc())
        if status is not None:
            q = q.where(CatalogProposalRow.status == status)
        if proposed_by is not None:
            q = q.where(CatalogProposalRow.proposed_by == proposed_by)
        return [_proposal(r) for r in await self._s.scalars(q)]

    async def target_exists(self, kind: str, target_id: UUID) -> bool:
        """Return whether the row to edit exists."""
        return await self._s.get(_TARGETS[kind], target_id) is not None

    async def set_logo(
        self, institution_id: UUID, *, zoom: float | None, fit: str | None
    ) -> bool:
        """Set the given logo fields of an institution; False when it is unknown."""
        row = await self._s.get(InstitutionRow, institution_id)
        if row is None:
            return False
        if zoom is not None:
            row.logo_zoom = zoom
        if fit is not None:
            row.logo_fit = fit
        await self._s.flush()
        return True

    async def apply(self, proposal: CatalogProposal) -> UUID:
        """Create or update the catalog row and publish it."""
        source = SourceRow(
            id=new_id(), kind="manual", url=proposal.source_url, redistributable=False
        )
        self._s.add(source)
        model = _TARGETS[proposal.kind]
        values = {**proposal.payload, "source_id": source.id}
        if proposal.kind == "institution":
            values.pop("source_id")
        values["status"] = "published"
        if proposal.target_id is not None:
            row = await self._s.get(model, proposal.target_id)
            if row is None:
                raise AdmissionConflictError()
            for k, v in values.items():
                setattr(row, k, v)
        else:
            row = model(id=new_id(), **values)
            self._s.add(row)
        await self._s.flush()
        return row.id  # type: ignore[no-any-return]

    async def save_review(
        self, proposal: CatalogProposal, *, expected_lock: int
    ) -> CatalogProposal:
        """Write the review; conflict if `lock_version` moved."""
        result = await self._s.execute(
            update(CatalogProposalRow)
            .where(
                CatalogProposalRow.id == proposal.id,
                CatalogProposalRow.lock_version == expected_lock,
                CatalogProposalRow.status == "pending",
            )
            .values(
                status=proposal.status,
                reviewed_by=proposal.reviewed_by,
                reviewed_at=proposal.reviewed_at,
                review_note=proposal.review_note,
                applied_id=proposal.applied_id,
                lock_version=expected_lock + 1,
            )
        )
        if result.rowcount == 0:  # type: ignore[attr-defined]
            raise AdmissionConflictError()
        row = await self._s.get(CatalogProposalRow, proposal.id)
        await self._s.refresh(row)
        assert row is not None
        return _proposal(row)
