"""Route of the Administration insights."""

from app.interfaces.http.v1.admin_insights.handlers.get_insights import get_insights
from app.interfaces.http.v1.admin_insights.schemas import InsightsResponse

from fastapi import APIRouter

router = APIRouter(prefix="/v1/admin", tags=["admin-insights"])

router.add_api_route(
    "/insights", get_insights, methods=["GET"], response_model=InsightsResponse
)
