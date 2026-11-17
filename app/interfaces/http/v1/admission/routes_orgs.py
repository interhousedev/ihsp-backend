"""Organizations tagged on opportunities and scholarships."""

from uuid import UUID

from app.interfaces.http.v1.admission.deps import AnyContext, ContainerDep
from app.interfaces.http.v1.admission.schemas_orgs import (
    OrgIn,
    OrgListOut,
    OrgOut,
    OrgPatch,
)

from fastapi import APIRouter, Response, status

router = APIRouter(prefix="/v1/admission", tags=["admission"])


async def list_orgs(container: ContainerDep, ctx: AnyContext) -> OrgListOut:
    """Every organization."""
    adm = container.admission
    return OrgListOut(
        items=[OrgOut.of(o) for o in await adm.orgs.list()],
        can_moderate=adm.opportunities.can_moderate(ctx),
    )


async def create_org(body: OrgIn, container: ContainerDep, ctx: AnyContext) -> OrgOut:
    """Create an organization (staff)."""
    org = await container.admission.orgs.create(ctx, **body.model_dump())
    return OrgOut.of(org)


async def update_org(
    org_id: UUID, body: OrgPatch, container: ContainerDep, ctx: AnyContext
) -> OrgOut:
    """Change an organization (staff)."""
    org = await container.admission.orgs.update(
        ctx, org_id, **body.model_dump(exclude_unset=True)
    )
    return OrgOut.of(org)


async def delete_org(
    org_id: UUID, container: ContainerDep, ctx: AnyContext
) -> Response:
    """Delete an organization no entry references (staff)."""
    await container.admission.orgs.delete(ctx, org_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


_R = router.add_api_route
_R(
    "/orgs",
    list_orgs,
    methods=["GET"],
    response_model=OrgListOut,
    operation_id="admission_list_orgs",
)
_R(
    "/staff/orgs",
    create_org,
    methods=["POST"],
    status_code=status.HTTP_201_CREATED,
    response_model=OrgOut,
    operation_id="admission_create_org",
)
_R(
    "/staff/orgs/{org_id}",
    update_org,
    methods=["PATCH"],
    response_model=OrgOut,
    operation_id="admission_update_org",
)
_R(
    "/staff/orgs/{org_id}",
    delete_org,
    methods=["DELETE"],
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    operation_id="admission_delete_org",
)
