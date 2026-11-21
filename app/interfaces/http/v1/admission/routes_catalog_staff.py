"""Staff catalog proposals and their review (`/v1/admission/staff/catalog/*`)."""

from typing import Annotated, Literal
from uuid import UUID

from app.interfaces.http.v1.admission.deps import AnyContext, ContainerDep
from app.interfaces.http.v1.admission.routes_chooser import Lang
from app.interfaces.http.v1.admission.routes_items import _locale
from app.interfaces.http.v1.admission.schemas_catalog_staff import (
    CatalogProposalIn,
    CatalogProposalListOut,
    CatalogProposalOut,
    CatalogReviewIn,
    FactSpecOut,
    InstitutionStatus,
    StaffInstitutionCreateIn,
    StaffInstitutionPageOut,
    StaffInstitutionPutIn,
    StaffInstitutionRowOut,
)
from app.modules.admission.domain.catalog_staff import (
    PAGE_DEFAULT,
    PAGE_MAX,
    QUERY_MAX,
)
from app.modules.admission.domain.intl_fact_display import fact_spec_view
from app.modules.identity.domain.personal_token import PersonalTokenScope

from fastapi import APIRouter, Query, Response, status

router = APIRouter(prefix="/v1/admission", tags=["admission"])


async def create_catalog_proposal(
    body: CatalogProposalIn, container: ContainerDep, ctx: AnyContext
) -> CatalogProposalOut:
    """Propose a catalog change with its source (§11)."""
    created = await container.admission.catalog_proposals.propose(
        ctx,
        kind=body.kind,
        target_id=body.target_id,
        fields=body.fields.model_dump(exclude_none=True),
        supp_prompts=[x.model_dump() for x in body.supp_prompts],
        facts={k: f.model_dump() for k, f in body.facts.items()},
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
        can_review=service.can_review(ctx)
        and PersonalTokenScope.ADMISSION_CATALOG.value not in ctx.actor.scopes,
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


async def catalog_fact_spec(
    container: ContainerDep, ctx: AnyContext, accept_language: Lang = None
) -> FactSpecOut:
    """The international facts the proposal form can fill, labelled by locale."""
    container.admission.catalog_proposals.require_proposer(ctx)
    groups = fact_spec_view(_locale(accept_language))
    return FactSpecOut.model_validate({"groups": groups})


async def list_staff_institutions(
    container: ContainerDep,
    ctx: AnyContext,
    q: Annotated[str | None, Query(max_length=QUERY_MAX)] = None,
    country: Annotated[str | None, Query(min_length=2, max_length=2)] = None,
    inst_status: Annotated[InstitutionStatus | None, Query(alias="status")] = None,
    page: Annotated[int, Query(ge=1, le=10000)] = 1,
    page_size: Annotated[int, Query(ge=1, le=PAGE_MAX)] = PAGE_DEFAULT,
) -> StaffInstitutionPageOut:
    """Every institution of any status, searchable by name, city or domain."""
    found = await container.admission.catalog_staff.search(
        ctx,
        query=q,
        country=country,
        status=inst_status,
        page=page,
        page_size=page_size,
    )
    return StaffInstitutionPageOut(
        items=[StaffInstitutionRowOut.of(i) for i in found.items],
        total=found.total,
        page=page,
        page_size=page_size,
        countries=found.countries,
    )


async def create_staff_institution(
    body: StaffInstitutionCreateIn, container: ContainerDep, ctx: AnyContext
) -> StaffInstitutionRowOut:
    """Add an institution directly (published unless `status` says otherwise)."""
    created = await container.admission.catalog_staff.create(
        ctx, body.model_dump(exclude_unset=True)
    )
    return StaffInstitutionRowOut.of(created)


async def put_staff_institution(
    institution_id: UUID,
    body: StaffInstitutionPutIn,
    container: ContainerDep,
    ctx: AnyContext,
) -> StaffInstitutionRowOut:
    """Edit an institution; omitted fields stay, `null` clears (409 if stale)."""
    saved = await container.admission.catalog_staff.update(
        ctx,
        institution_id,
        body.model_dump(exclude_unset=True, exclude={"lock_version"}),
        lock_version=body.lock_version,
    )
    return StaffInstitutionRowOut.of(saved)


async def delete_staff_institution(
    institution_id: UUID, container: ContainerDep, ctx: AnyContext
) -> Response:
    """Delete an unused institution (409 `admission/catalog_in_use` otherwise)."""
    await container.admission.catalog_staff.delete(ctx, institution_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


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
_R(
    "/staff/catalog/fact-spec",
    catalog_fact_spec,
    methods=["GET"],
    response_model=FactSpecOut,
    operation_id="admission_catalog_fact_spec",
)
_R(
    "/staff/catalog/institutions",
    list_staff_institutions,
    methods=["GET"],
    response_model=StaffInstitutionPageOut,
    operation_id="admission_staff_institutions_list",
)
_R(
    "/staff/catalog/institutions",
    create_staff_institution,
    methods=["POST"],
    status_code=status.HTTP_201_CREATED,
    response_model=StaffInstitutionRowOut,
    operation_id="admission_staff_institutions_create",
)
_R(
    "/staff/catalog/institutions/{institution_id}",
    put_staff_institution,
    methods=["PUT"],
    response_model=StaffInstitutionRowOut,
    operation_id="admission_staff_institutions_put",
)
_R(
    "/staff/catalog/institutions/{institution_id}",
    delete_staff_institution,
    methods=["DELETE"],
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    operation_id="admission_staff_institutions_delete",
)
