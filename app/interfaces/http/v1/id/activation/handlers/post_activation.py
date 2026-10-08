"""POST /v1/id/activation/{token}: set the password and activate."""

from app.interfaces.http.v1.id.activation.schemas import (
    ActivateBody,
    RedirectResponseBody,
)
from app.interfaces.http.v1.id.dependencies import AuthDep, CtxDep


async def post_activation(
    token: str, body: ActivateBody, auth: AuthDep, ctx: CtxDep
) -> RedirectResponseBody:
    """Activate the account and say where to go next."""
    redirect = await auth.activate_account.execute(
        token,
        password=body.password,
        email=str(body.email) if body.email else None,
        email_code=body.email_code,
        ctx=ctx,
    )
    return RedirectResponseBody(redirect_to=redirect)
