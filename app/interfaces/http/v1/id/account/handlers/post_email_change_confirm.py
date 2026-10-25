"""POST /v1/id/me/email/change/confirm: switch the recovery email."""

from app.interfaces.http.v1.id.account.schemas import CodeBody, UserMeResponse
from app.interfaces.http.v1.id.dependencies import ActorDep, AuthDep, CtxDep


async def post_email_change_confirm(
    body: CodeBody, actor: ActorDep, auth: AuthDep, ctx: CtxDep
) -> UserMeResponse:
    """Verify the code and return the updated account."""
    await auth.confirm_email_change.execute(actor, body.code, ctx)
    return UserMeResponse.of(await auth.get_me.execute(actor))
