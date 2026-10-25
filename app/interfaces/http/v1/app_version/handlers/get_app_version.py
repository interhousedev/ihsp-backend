"""GET /v1/app/version."""

from typing import Annotated

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_container
from app.interfaces.http.v1.app_version.schemas import AppVersionResponse

from fastapi import Depends, Response

NO_STORE = "no-store"  # the app must always see the current numbers


async def get_app_version(
    response: Response,
    container: Annotated[Container, Depends(get_container)],
) -> AppVersionResponse:
    """Return the latest and the minimum supported app version; public, never cached."""
    response.headers["Cache-Control"] = NO_STORE
    versions = container.settings.app
    return AppVersionResponse(
        latest=versions.latest, min_supported=versions.min_supported
    )
