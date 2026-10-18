"""Route of the Administration logs."""

from app.interfaces.http.v1.admin_logs.handlers.list_issues import list_issues
from app.interfaces.http.v1.admin_logs.schemas import LogIssuesPage

from fastapi import APIRouter

router = APIRouter(prefix="/v1/admin/logs", tags=["admin-logs"])

router.add_api_route(
    "/issues", list_issues, methods=["GET"], response_model=LogIssuesPage
)
