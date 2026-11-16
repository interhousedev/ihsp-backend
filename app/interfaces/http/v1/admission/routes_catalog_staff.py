"""Staff catalog proposals and their review (`/v1/admission/staff/catalog/*`)."""

from typing import Annotated, Literal
from uuid import UUID

from app.interfaces.http.v1.admission.deps import AnyContext, ContainerDep
from app.interfaces.http.v1.admission.schemas_catalog_staff import (
    CatalogProposalIn,
    CatalogProposalListOut,
    CatalogProposalOut,
    CatalogReviewIn,
)

from fastapi import APIRouter, Query, status

router = APIRouter(prefix="/v1/admission", tags=["admission"])


async def create_catalog_proposal(
    body: CatalogProposalIn, container: ContainerDep, ctx: AnyContext
) -> CatalogProposalOut:
    """Propose a catalog change with its source (§11)."""
    created = await container.admission.catalog_proposals.propose(
        ctx,
        kind=body.kind,
        target_id=body.target_id,
        fields=body.fields,
        source_url=body.source_url,
        note=body.note,
    )
    return CatalogProposalOut.of(created)


async def list_catalog_proposals(
    container: ContainerDep,
    ctx: AnyContext,
    proposal_status: Annotated[
        Literal["pending", "approved", "rejected"] | None,
        Query(alias="status"),
    ] = None,
) -> CatalogProposalListOut:
    """Every proposal for a curator, the caller's own for other staff."""
    service = container.admission.catalog_proposals
    items = await service.list(ctx, status=proposal_status)
    return CatalogProposalListOut(
        items=[CatalogProposalOut.of(p) for p in items],
        can_review=service.can_review(ctx),
    )


async def review_catalog_proposal(
    proposal_id: UUID,
    body: CatalogReviewIn,
    container: ContainerDep,
    ctx: AnyContext,
) -> CatalogProposalOut:
    """Approve (publishing the change) or reject a pending proposal."""
    reviewed = await container.admission.catalog_proposals.review(
        ctx,
        proposal_id,
        approve=body.approve,
        note=body.note,
        lock_version=body.lock_version,
    )
    return CatalogProposalOut.of(reviewed)


_R = router.add_api_route
_R(
    "/staff/catalog/proposals",
    create_catalog_proposal,
    methods=["POST"],
    status_code=status.HTTP_201_CREATED,
    response_model=CatalogProposalOut,
    operation_id="admission_create_catalog_proposal",
)
_R(
    "/staff/catalog/proposals",
    list_catalog_proposals,
    methods=["GET"],
    response_model=CatalogProposalListOut,
    operation_id="admission_list_catalog_proposals",
)
_R(
    "/staff/catalog/proposals/{proposal_id}/review",
    review_catalog_proposal,
    methods=["POST"],
    response_model=CatalogProposalOut,
    operation_id="admission_review_catalog_proposal",
)
