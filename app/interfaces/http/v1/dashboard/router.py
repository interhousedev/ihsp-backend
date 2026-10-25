"""Routes of the dashboard (`/v1/me/dashboard`)."""

from app.interfaces.http.v1.dashboard.handlers.get_dashboard import get_dashboard
from app.interfaces.http.v1.dashboard.handlers.put_dashboard import put_dashboard

from fastapi import APIRouter

router = APIRouter(prefix="/v1/me", tags=["dashboard"])

router.add_api_route("/dashboard", get_dashboard, methods=["GET"])
router.add_api_route("/dashboard", put_dashboard, methods=["PUT"])
