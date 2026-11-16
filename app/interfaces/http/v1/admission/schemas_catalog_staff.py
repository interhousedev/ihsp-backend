"""Schemas of the staff catalog proposals (`/v1/admission/staff/catalog/*`)."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from app.modules.admission.domain.catalog_proposals import CatalogProposal

from pydantic import BaseModel, Field


class CatalogProposalIn(BaseModel):
    """Propose a new institution or scholarship, or an edit of an existing one."""

    kind: Literal["institution", "scholarship"]
    target_id: UUID | None = None
    fields: dict[str, Any]
    source_url: str = Field(max_length=2000)
    note: str | None = Field(default=None, max_length=1000)


class CatalogReviewIn(BaseModel):
    """Approve or reject a pending proposal."""

    approve: bool
    note: str | None = Field(default=None, max_length=500)
    lock_version: int


class CatalogProposalOut(BaseModel):
    """A stored proposal."""

    id: UUID
    kind: Literal["institution", "scholarship"]
    target_id: UUID | None
    fields: dict[str, Any]
    source_url: str
    note: str | None
    status: Literal["pending", "approved", "rejected"]
    proposed_by: UUID
    created_at: datetime
    reviewed_by: UUID | None
    reviewed_at: datetime | None
    review_note: str | None
    applied_id: UUID | None
    lock_version: int

    @classmethod
    def of(cls, p: CatalogProposal) -> "CatalogProposalOut":
        """Map a proposal."""
        return cls(
            id=p.id,
            kind=p.kind,
            target_id=p.target_id,
            fields=p.payload,
            source_url=p.source_url,
            note=p.note,
            status=p.status,
            proposed_by=p.proposed_by,
            created_at=p.created_at,
            reviewed_by=p.reviewed_by,
            reviewed_at=p.reviewed_at,
            review_note=p.review_note,
            applied_id=p.applied_id,
            lock_version=p.lock_version,
        )


class CatalogProposalListOut(BaseModel):
    """Proposals the caller may see, and whether the caller may review them."""

    items: list[CatalogProposalOut]
    can_review: bool
