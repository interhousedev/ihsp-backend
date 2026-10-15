"""POST /v1/id/recovery/password/confirm: set a new password."""

from app.interfaces.http.v1.id.dependencies import AuthDep, CtxDep
from app.interfaces.http.v1.id.recovery.schemas import (
    PasswordConfirmBody,
    PasswordConfirmResponse,
)


async def post_password_confirm(
    body: PasswordConfirmBody, auth: AuthDep, ctx: CtxDep
) -> PasswordConfirmResponse:
    """Change the password, log out everywhere, hand a ticket to sign in here."""
    ticket = await auth.confirm_password_reset.execute(
        body.login_or_email, body.code, body.new_password, ctx
    )
    return PasswordConfirmResponse(login_ticket=ticket)
