"""POST /v1/oauth/token-hook: Hydra asks before issuing a token."""

import hmac
from typing import Annotated, Any

from app.interfaces.http.v1.id.dependencies import AuthDep, ContainerDep
from app.shared.base_error import UnauthorizedError

from fastapi import Header, Response
from fastapi.responses import JSONResponse


def _check_service_token(authorization: str, expected: str) -> None:
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(token, expected):
        raise UnauthorizedError(support_details="bad token hook credentials")


async def post_token_hook(
    payload: dict[str, Any],
    auth: AuthDep,
    container: ContainerDep,
    authorization: Annotated[str, Header()] = "",
) -> Response:
    """200 with the full claims, 204 unchanged, or 403 to deny the token."""
    _check_service_token(
        authorization, container.settings.tokens.service_token.get_secret_value()
    )
    result = await auth.handle_token_hook.execute(payload)
    if result.action == "deny":
        return Response(status_code=403)
    if result.action == "unchanged":
        return Response(status_code=204)
    return JSONResponse({"session": result.session})
