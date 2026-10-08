"""POST /v1/id/recovery/password/request: always 202."""

from app.interfaces.http.v1.id.dependencies import AuthDep, CtxDep
from app.interfaces.http.v1.id.recovery.schemas import PasswordRequestBody

from fastapi import Response


async def post_password_request(
    body: PasswordRequestBody, auth: AuthDep, ctx: CtxDep
) -> Response:
    """Send a reset code if the account qualifies; say nothing either way."""
    await auth.request_password_reset.execute(body.login_or_email, ctx)
    return Response(status_code=202)
