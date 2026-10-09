"""App version route: the installed app checks it on start and on resume (PWA-3)."""

from app.interfaces.http.v1.app_version.handlers.get_app_version import (
    get_app_version,
)
from app.interfaces.http.v1.app_version.schemas import AppVersionResponse

from fastapi import APIRouter

router = APIRouter(prefix="/v1/app", tags=["app"])

router.add_api_route(
    "/version",
    get_app_version,
    methods=["GET"],
    response_model=AppVersionResponse,
)
