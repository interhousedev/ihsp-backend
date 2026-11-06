"""GET /v1/oauth/mcp/redirect-sync: nginx calls it before Hydra's /oauth2/auth."""

from app.interfaces.http.v1.id.dependencies import AuthDep

import structlog
from fastapi import APIRouter, Response

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/v1/oauth/mcp", tags=["oauth"])


@router.get("/redirect-sync", status_code=204, response_class=Response)
async def redirect_sync(
    auth: AuthDep, client_id: str = "", redirect_uri: str = ""
) -> Response:
    """Always 204: Hydra stays the one that accepts or refuses the request."""
    try:
        await auth.sync_gemini_redirect.execute(client_id, redirect_uri)
    except Exception:  # noqa: BLE001  a failure must never block the login
        log.exception("mcp_redirect_sync_failed")
    return Response(status_code=204)
