"""POST /v1/oauth/token: exchange the authorization code."""

from app.interfaces.http.cors import require_client_header
from app.interfaces.http.v1.id.dependencies import AuthDep, ContainerDep
from app.interfaces.http.v1.oauth.tokens.cookies import set_refresh_cookie
from app.interfaces.http.v1.oauth.tokens.schemas import TokenBody, TokenResponse

from fastapi import Request, Response


async def post_token(
    body: TokenBody,
    request: Request,
    response: Response,
    auth: AuthDep,
    container: ContainerDep,
) -> TokenResponse:
    """Access token in the body, refresh token in an HttpOnly cookie."""
    require_client_header(request)
    grant = await auth.exchange_code.execute(
        body.client_id, body.code, body.code_verifier, body.redirect_uri
    )
    if grant.refresh_token:
        set_refresh_cookie(
            response, container.settings, body.client_id, grant.refresh_token
        )
    return TokenResponse.of(grant)
