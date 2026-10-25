"""POST /v1/id/login/ticket: sign in right after a registration or password reset."""

from app.interfaces.http.v1.id.dependencies import AuthDep, CtxDep
from app.interfaces.http.v1.id.login.schemas import LoginTicketBody, RedirectToResponse


async def post_login_ticket(
    body: LoginTicketBody, auth: AuthDep, ctx: CtxDep
) -> RedirectToResponse:
    """Redeem the one-time ticket on this login challenge (remembered device)."""
    redirect = await auth.login_acceptor.redeem_ticket(
        body.login_challenge, body.ticket, ip=ctx.ip, user_agent=ctx.user_agent
    )
    return RedirectToResponse(redirect_to=redirect)
