"""Routes /v1/admin/settings (Administration only)."""

from typing import Annotated

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_container, require_roles
from app.interfaces.http.v1.admin_settings.schemas import (
    PlatformSettingsBody,
    PlatformSettingsResponse,
)
from app.shared.actor import Actor, Role

from fastapi import APIRouter, Depends

router = APIRouter(prefix="/v1/admin/settings", tags=["admin-settings"])

ContainerDep = Annotated[Container, Depends(get_container)]
AdminActor = Annotated[Actor, Depends(require_roles(Role.ADMIN))]


@router.get("", response_model=PlatformSettingsResponse)
async def get_settings(
    container: ContainerDep, actor: AdminActor
) -> PlatformSettingsResponse:
    """Return the runtime settings and the feature flags."""
    current = await container.admin.platform_settings.get(actor)
    return PlatformSettingsResponse.of(current, container.settings.features)


@router.put("", response_model=PlatformSettingsResponse)
async def put_settings(
    body: PlatformSettingsBody, container: ContainerDep, actor: AdminActor
) -> PlatformSettingsResponse:
    """Save every editable setting."""
    updated = await container.admin.platform_settings.update(actor, body.model_dump())
    return PlatformSettingsResponse.of(updated, container.settings.features)
