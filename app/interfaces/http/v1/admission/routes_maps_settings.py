"""Map link template of "open on a map" (`/v1/admission/settings/maps-url`)."""

from app.interfaces.http.v1.admission.deps import AdmissionCtx, ContainerDep
from app.modules.admission.domain.rankings import DEFAULT_MAPS_TEMPLATE

from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter(prefix="/v1/admission", tags=["admission"])


class MapsUrlIn(BaseModel):
    """An https template with one `{query}`; null restores the default."""

    template: str | None = Field(default=None, max_length=300)


class MapsUrlOut(BaseModel):
    """The stored template (null: default) and the default."""

    template: str | None
    default: str = DEFAULT_MAPS_TEMPLATE


async def get_maps_url(container: ContainerDep, ctx: AdmissionCtx) -> MapsUrlOut:
    """The map link template in force."""
    return MapsUrlOut(template=await container.admission.maps_settings.get())


async def put_maps_url(
    body: MapsUrlIn, container: ContainerDep, ctx: AdmissionCtx
) -> MapsUrlOut:
    """Replace the template (administrators)."""
    saved = await container.admission.maps_settings.set(ctx, body.template)
    return MapsUrlOut(template=saved)


router.add_api_route(
    "/settings/maps-url",
    get_maps_url,
    methods=["GET"],
    response_model=MapsUrlOut,
    operation_id="admission_maps_url",
)
router.add_api_route(
    "/settings/maps-url",
    put_maps_url,
    methods=["PUT"],
    response_model=MapsUrlOut,
    operation_id="admission_set_maps_url",
)
