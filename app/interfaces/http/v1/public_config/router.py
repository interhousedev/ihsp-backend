"""Route GET /v1/public/client-config (no sign-in: the id app reads it)."""

from datetime import datetime
from typing import Annotated

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_container
from app.shared.features import Feature, is_enabled

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel

router = APIRouter(prefix="/v1/public", tags=["public"])


class ClientFeatures(BaseModel):
    """Feature flags the web apps need before sign-in."""

    login_cues: bool


class ClientDocs(BaseModel):
    """Links to the documentation pages; null when not configured."""

    personal_tokens_url: str | None
    entrance_devices_url: str | None


class ClientConfigResponse(BaseModel):
    """Public client configuration."""

    features: ClientFeatures
    docs: ClientDocs


@router.get("/client-config", response_model=ClientConfigResponse)
async def get_client_config(
    container: Annotated[Container, Depends(get_container)],
) -> ClientConfigResponse:
    """Return the public feature flags and documentation links."""
    docs = container.settings.docs
    return ClientConfigResponse(
        features=ClientFeatures(
            login_cues=is_enabled(container.settings, Feature.LOGIN_CUES)
        ),
        docs=ClientDocs(
            personal_tokens_url=docs.personal_tokens_url,
            entrance_devices_url=docs.entrance_devices_url,
        ),
    )


class MaintenanceResponse(BaseModel):
    """Whether the platform is read-only because it is being moved to a new server."""

    active: bool
    since: datetime | None
    moved: bool
    target_url: str | None


@router.get("/maintenance", response_model=MaintenanceResponse)
async def get_maintenance(
    container: Annotated[Container, Depends(get_container)], response: Response
) -> MaintenanceResponse:
    """Return the maintenance state the web apps show as a banner (never cached)."""
    response.headers["Cache-Control"] = "no-store"
    admin = container.admin
    info = admin.migration.info() if admin is not None else None
    if info is None or not info.active:
        return MaintenanceResponse(
            active=False, since=None, moved=False, target_url=None
        )
    return MaintenanceResponse(
        active=True, since=info.since, moved=info.moved, target_url=info.target_url
    )
