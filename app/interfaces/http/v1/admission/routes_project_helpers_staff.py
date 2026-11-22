"""Curation of project helpers (`/v1/admission/staff/project-helpers`)."""

from uuid import UUID

from app.interfaces.http.v1.admission.deps import AnyContext, ContainerDep
from app.interfaces.http.v1.admission.schemas_projects import (
    HelperIn,
    HelperListOut,
    HelperOut,
)

from fastapi import APIRouter, Response, status

router = APIRouter(prefix="/v1/admission/staff/project-helpers", tags=["admission"])


async def list_helpers(container: ContainerDep, ctx: AnyContext) -> HelperListOut:
    """Every helper, inactive ones too (curators only)."""
    rows = await container.admission.project_helpers.list_all(ctx)
    return HelperListOut(items=[HelperOut.of(h) for h in rows])


async def create_helper(
    body: HelperIn, container: ContainerDep, ctx: AnyContext
) -> HelperOut:
    """Add a helper."""
    saved = await container.admission.project_helpers.create(ctx, body.values())
    return HelperOut.of(saved)


async def update_helper(
    helper_id: UUID, body: HelperIn, container: ContainerDep, ctx: AnyContext
) -> HelperOut:
    """Replace a helper."""
    saved = await container.admission.project_helpers.update(
        ctx, helper_id, body.values()
    )
    return HelperOut.of(saved)


async def delete_helper(
    helper_id: UUID, container: ContainerDep, ctx: AnyContext
) -> Response:
    """Delete a helper."""
    await container.admission.project_helpers.delete(ctx, helper_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


_R = router.add_api_route
_R(
    "",
    list_helpers,
    methods=["GET"],
    response_model=HelperListOut,
    operation_id="admission_staff_project_helpers_list",
)
_R(
    "",
    create_helper,
    methods=["POST"],
    response_model=HelperOut,
    status_code=status.HTTP_201_CREATED,
    operation_id="admission_staff_project_helpers_create",
)
_R(
    "/{helper_id}",
    update_helper,
    methods=["PUT"],
    response_model=HelperOut,
    operation_id="admission_staff_project_helpers_update",
)
_R(
    "/{helper_id}",
    delete_helper,
    methods=["DELETE"],
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    operation_id="admission_staff_project_helpers_delete",
)
