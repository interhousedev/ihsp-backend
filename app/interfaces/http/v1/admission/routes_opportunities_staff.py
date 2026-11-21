"""Staff table of opportunities (`/v1/admission/staff/opportunities`)."""

from typing import Annotated
from uuid import UUID

from app.interfaces.http.v1.admission.deps import AnyContext, ContainerDep
from app.interfaces.http.v1.admission.schemas_opportunities import Kind
from app.interfaces.http.v1.admission.schemas_opportunities_staff import (
    StaffOpportunityIn,
    StaffOpportunityOut,
    StaffOpportunityPageOut,
    StaffOpportunityPutIn,
    StaffOpportunityRowOut,
    StaffOpportunityVisibilityIn,
)
from app.modules.admission.domain.catalog_staff import (
    PAGE_DEFAULT,
    PAGE_MAX,
    QUERY_MAX,
    OpportunityState,
)

from fastapi import APIRouter, Query, Response, status

router = APIRouter(prefix="/v1/admission", tags=["admission"])


async def list_staff_opportunities(
    container: ContainerDep,
    ctx: AnyContext,
    q: Annotated[str | None, Query(max_length=QUERY_MAX)] = None,
    kind: Kind | None = None,
    state: OpportunityState = "all",
    page: Annotated[int, Query(ge=1, le=10000)] = 1,
    page_size: Annotated[int, Query(ge=1, le=PAGE_MAX)] = PAGE_DEFAULT,
) -> StaffOpportunityPageOut:
    """Every entry, live and hidden, searchable by title or provider."""
    items, total = await container.admission.opportunities_staff.search(
        ctx, query=q, kind=kind, state=state, page=page, page_size=page_size
    )
    return StaffOpportunityPageOut(
        items=[StaffOpportunityRowOut.of(o) for o in items],
        total=total,
        page=page,
        page_size=page_size,
    )


async def get_staff_opportunity(
    opportunity_id: UUID, container: ContainerDep, ctx: AnyContext
) -> StaffOpportunityOut:
    """One entry with all its fields."""
    found, in_use = await container.admission.opportunities_staff.get(
        ctx, opportunity_id
    )
    return StaffOpportunityOut.of(found, in_use)


async def create_staff_opportunity(
    body: StaffOpportunityIn, container: ContainerDep, ctx: AnyContext
) -> StaffOpportunityOut:
    """Publish a new entry without moderation."""
    created = await container.admission.opportunities_staff.create(
        ctx, body.fields.draft(None)
    )
    return StaffOpportunityOut.of(created, False)


async def put_staff_opportunity(
    opportunity_id: UUID,
    body: StaffOpportunityPutIn,
    container: ContainerDep,
    ctx: AnyContext,
) -> StaffOpportunityOut:
    """Overwrite every field of an entry (409 when `lock_version` is stale)."""
    service = container.admission.opportunities_staff
    await service.update(
        ctx, opportunity_id, body.fields.draft(None), lock_version=body.lock_version
    )
    found, in_use = await service.get(ctx, opportunity_id)
    return StaffOpportunityOut.of(found, in_use)


async def set_staff_opportunity_visibility(
    opportunity_id: UUID,
    body: StaffOpportunityVisibilityIn,
    container: ContainerDep,
    ctx: AnyContext,
) -> StaffOpportunityOut:
    """Hide an entry from students or bring it back."""
    service = container.admission.opportunities_staff
    await service.set_archived(ctx, opportunity_id, body.archived)
    found, in_use = await service.get(ctx, opportunity_id)
    return StaffOpportunityOut.of(found, in_use)


async def delete_staff_opportunity(
    opportunity_id: UUID, container: ContainerDep, ctx: AnyContext
) -> Response:
    """Delete an unused entry (409 `admission/catalog_in_use` otherwise)."""
    await container.admission.opportunities_staff.delete(ctx, opportunity_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


_R = router.add_api_route
_R(
    "/staff/opportunities",
    list_staff_opportunities,
    methods=["GET"],
    response_model=StaffOpportunityPageOut,
    operation_id="admission_staff_opportunities_list",
)
_R(
    "/staff/opportunities",
    create_staff_opportunity,
    methods=["POST"],
    status_code=status.HTTP_201_CREATED,
    response_model=StaffOpportunityOut,
    operation_id="admission_staff_opportunities_create",
)
_R(
    "/staff/opportunities/{opportunity_id}",
    get_staff_opportunity,
    methods=["GET"],
    response_model=StaffOpportunityOut,
    operation_id="admission_staff_opportunities_get",
)
_R(
    "/staff/opportunities/{opportunity_id}",
    put_staff_opportunity,
    methods=["PUT"],
    response_model=StaffOpportunityOut,
    operation_id="admission_staff_opportunities_put",
)
_R(
    "/staff/opportunities/{opportunity_id}/visibility",
    set_staff_opportunity_visibility,
    methods=["POST"],
    response_model=StaffOpportunityOut,
    operation_id="admission_staff_opportunities_visibility",
)
_R(
    "/staff/opportunities/{opportunity_id}",
    delete_staff_opportunity,
    methods=["DELETE"],
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    operation_id="admission_staff_opportunities_delete",
)
