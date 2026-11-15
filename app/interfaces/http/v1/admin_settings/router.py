"""Routes /v1/admin/settings (Administration only)."""

from typing import Annotated

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_container, require_roles
from app.interfaces.http.v1.admin_settings.schemas import (
    PlatformSettingsBody,
    PlatformSettingsResponse,
)
from app.modules.admin.domain.lyceum_logo import MAX_LOGO_BYTES
from app.shared.actor import Actor, Role

from fastapi import APIRouter, Depends, File, UploadFile

router = APIRouter(prefix="/v1/admin/settings", tags=["admin-settings"])

ContainerDep = Annotated[Container, Depends(get_container)]
AdminActor = Annotated[Actor, Depends(require_roles(Role.ADMIN))]


@router.get("", response_model=PlatformSettingsResponse)
async def get_settings(
    container: ContainerDep, actor: AdminActor
) -> PlatformSettingsResponse:
    """Return the runtime settings and the feature flags."""
    current = await container.admin.platform_settings.get(actor)
    return PlatformSettingsResponse.of(
        current,
        container.settings.features,
        await container.admin.lyceum_logo.current(),
    )


@router.put("", response_model=PlatformSettingsResponse)
async def put_settings(
    body: PlatformSettingsBody, container: ContainerDep, actor: AdminActor
) -> PlatformSettingsResponse:
    """Save every editable setting."""
    updated = await container.admin.platform_settings.update(
        actor, body.model_dump(exclude_none=True)
    )
    return PlatformSettingsResponse.of(
        updated,
        container.settings.features,
        await container.admin.lyceum_logo.current(),
    )


@router.put("/lyceum-logo", response_model=PlatformSettingsResponse)
async def put_lyceum_logo(
    container: ContainerDep,
    actor: AdminActor,
    file: Annotated[UploadFile, File()],
) -> PlatformSettingsResponse:
    """Upload the lyceum logo (PNG, JPEG or WebP, at most 1 MiB)."""
    data = await file.read(MAX_LOGO_BYTES + 1)
    logo = await container.admin.lyceum_logo.upload(actor, data)
    current = await container.admin.platform_settings.get(actor)
    return PlatformSettingsResponse.of(current, container.settings.features, logo)


@router.delete("/lyceum-logo", response_model=PlatformSettingsResponse)
async def delete_lyceum_logo(
    container: ContainerDep, actor: AdminActor
) -> PlatformSettingsResponse:
    """Remove the lyceum logo."""
    await container.admin.lyceum_logo.clear(actor)
    current = await container.admin.platform_settings.get(actor)
    return PlatformSettingsResponse.of(current, container.settings.features, None)
