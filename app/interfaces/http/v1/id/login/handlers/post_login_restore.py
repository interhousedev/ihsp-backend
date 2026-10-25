"""POST /v1/id/login/restore[/decline]: an account scheduled for deletion."""

from app.interfaces.http.v1.id.dependencies import AuthDep, CtxDep
from app.interfaces.http.v1.id.login.schemas import (
    LoginResultResponse,
    RedirectToResponse,
    RestoreBody,
)


async def post_login_restore(
    body: RestoreBody, auth: AuthDep, ctx: CtxDep
) -> LoginResultResponse:
    """Cancel the deletion with the ticket of the login step, then sign in."""
    result = await auth.restore_account_at_login.execute(
        body.login_challenge, body.ticket, ctx=ctx
    )
    return LoginResultResponse.of(result)


async def post_login_restore_decline(
    body: RestoreBody, auth: AuthDep
) -> RedirectToResponse:
    """Keep the deletion: reject the login challenge."""
    redirect = await auth.decline_account_restore.execute(
        body.login_challenge, body.ticket
    )
    return RedirectToResponse(redirect_to=redirect)
