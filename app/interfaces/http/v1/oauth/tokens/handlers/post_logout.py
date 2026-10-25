"""POST /v1/oauth/logout: revoke the refresh token and clear the cookie."""

from app.interfaces.http.cors import require_client_header
from app.interfaces.http.v1.id.dependencies import AuthDep, ContainerDep
from app.interfaces.http.v1.oauth.tokens.cookies import (
    clear_refresh_cookie,
    read_refresh_cookie,
)
from app.interfaces.http.v1.oauth.tokens.schemas import ClientBody, LogoutResponse

from fastapi import Request, Response


async def post_logout(
    body: ClientBody,
    request: Request,
    response: Response,
    auth: AuthDep,
    container: ContainerDep,
) -> LogoutResponse:
    """Return Hydra's end-session URL for the browser to open."""
    require_client_header(request)
    settings = container.settings
    token = read_refresh_cookie(request, settings, body.client_id)
    logout_url = await auth.log_out_client.execute(body.client_id, token)
    clear_refresh_cookie(response, settings, body.client_id)
    return LogoutResponse(logout_url=logout_url)
