"""POST /v1/id/recovery/login: email the login, always 202."""

from app.interfaces.http.v1.id.dependencies import AuthDep, CtxDep
from app.interfaces.http.v1.id.recovery.schemas import LoginRecoveryBody

from fastapi import Response


async def post_login_recovery(
    body: LoginRecoveryBody, auth: AuthDep, ctx: CtxDep
) -> Response:
    """Send the login to the recovery email if it matches an account."""
    await auth.send_login_reminder.execute(str(body.email), ctx)
    return Response(status_code=202)
