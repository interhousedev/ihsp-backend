"""Routes of the administrators' MCP activity pages."""

from app.interfaces.http.v1.admin_mcp.handlers.get_summary import get_summary
from app.interfaces.http.v1.admin_mcp.handlers.list_activity import list_activity
from app.interfaces.http.v1.admin_mcp.schemas import (
    AdminMcpActivityPage,
    McpActivitySummary,
)

from fastapi import APIRouter

router = APIRouter(prefix="/v1/admin/mcp", tags=["admin-mcp"])

router.add_api_route(
    "/activity", list_activity, methods=["GET"], response_model=AdminMcpActivityPage
)
router.add_api_route(
    "/activity/summary",
    get_summary,
    methods=["GET"],
    response_model=McpActivitySummary,
)
