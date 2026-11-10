"""App map route: where every feature lives, filtered by the caller's roles."""

from app.interfaces.http.v1.app_map.handlers.get_app_map import get_app_map
from app.interfaces.http.v1.app_map.schemas import AppMapResponse

from fastapi import APIRouter

router = APIRouter(prefix="/v1", tags=["app"])

router.add_api_route(
    "/app-map",
    get_app_map,
    methods=["GET"],
    response_model=AppMapResponse,
)
