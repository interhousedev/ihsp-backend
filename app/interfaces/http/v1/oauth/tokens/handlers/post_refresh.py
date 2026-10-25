"""POST /v1/oauth/refresh: rotate the refresh token from the cookie."""

from app.interfaces.http.cors import require_client_header
from app.interfaces.http.errors import problem_response
from app.interfaces.http.v1.id.dependencies import AuthDep, ContainerDep
from app.interfaces.http.v1.oauth.tokens.cookies import (
    clear_refresh_cookie,
    read_refresh_cookie,
    set_refresh_cookie,
)
from app.interfaces.http.v1.oauth.tokens.schemas import ClientBody, TokenResponse
from app.shared.base_error import UnauthorizedError

from fastapi import Request, Response
from fastapi.responses import JSONResponse


def _unauthorized(exc: UnauthorizedError) -> JSONResponse:
    return problem_response(
        exc.status,
        {
            "type": exc.code,
            "title": "Unauthorized",
            "status": exc.status,
            "message_key": exc.message_key,
            "params": exc.params,
        },
    )


async def post_refresh(
    body: ClientBody,
    request: Request,
    response: Response,
    auth: AuthDep,
    container: ContainerDep,
) -> TokenResponse | JSONResponse:
    """New access token; a bad refresh token clears the cookie and answers 401."""
    require_client_header(request)
    settings = container.settings
    token = read_refresh_cookie(request, settings, body.client_id)
    try:
        if token is None:
            raise UnauthorizedError(support_details="no refresh cookie")
        grant = await auth.refresh_tokens.execute(body.client_id, token)
    except UnauthorizedError as exc:
        failure = _unauthorized(exc)
        clear_refresh_cookie(failure, settings, body.client_id)
        return failure
    if grant.refresh_token:
        set_refresh_cookie(response, settings, body.client_id, grant.refresh_token)
    return TokenResponse.of(grant)
