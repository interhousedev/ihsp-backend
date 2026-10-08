"""Routes of the student composition endpoints."""

from app.interfaces.http.v1.composition.handlers.create_calendar_token import (
    create_calendar_token,
)
from app.interfaces.http.v1.composition.handlers.get_alerts import get_alerts
from app.interfaces.http.v1.composition.handlers.search import search
from app.interfaces.http.v1.composition.schemas import (
    AlertResponse,
    CalendarTokenResponse,
    SearchResultsResponse,
)

from fastapi import APIRouter

router = APIRouter(prefix="/v1/me", tags=["composition"])

router.add_api_route(
    "/alerts", get_alerts, methods=["GET"], response_model=list[AlertResponse]
)
router.add_api_route(
    "/search", search, methods=["GET"], response_model=SearchResultsResponse
)
router.add_api_route(
    "/calendar-token",
    create_calendar_token,
    methods=["POST"],
    response_model=CalendarTokenResponse,
)
