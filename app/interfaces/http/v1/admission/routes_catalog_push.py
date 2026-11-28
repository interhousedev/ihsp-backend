"""Bulk catalog push for curators and their write tokens (`.../staff/catalog/push`)."""

from app.interfaces.http.v1.admission.deps import AnyContext, ContainerDep
from app.interfaces.http.v1.admission.schemas_catalog_push import (
    CountryPushIn,
    InstitutionPushIn,
    PushResultListOut,
)

from fastapi import APIRouter

router = APIRouter(prefix="/v1/admission", tags=["admission"])


async def push_catalog_countries(
    body: CountryPushIn, container: ContainerDep, ctx: AnyContext
) -> PushResultListOut:
    """Upsert country facts by ISO code as drafts; verified ones are skipped."""
    results = await container.admission.catalog_push.push_countries(
        ctx,
        [i.model_dump() for i in body.items],
        overwrite_verified=body.overwrite_verified,
    )
    return PushResultListOut.of(results)


async def push_catalog_institutions(
    body: InstitutionPushIn, container: ContainerDep, ctx: AnyContext
) -> PushResultListOut:
    """Upsert institutions in the seed shape by slug."""
    results = await container.admission.catalog_push.push_institutions(ctx, body.items)
    return PushResultListOut.of(results)


_R = router.add_api_route
_R(
    "/staff/catalog/push/countries",
    push_catalog_countries,
    methods=["POST"],
    response_model=PushResultListOut,
    operation_id="admission_catalog_push_countries",
)
_R(
    "/staff/catalog/push/institutions",
    push_catalog_institutions,
    methods=["POST"],
    response_model=PushResultListOut,
    operation_id="admission_catalog_push_institutions",
)
