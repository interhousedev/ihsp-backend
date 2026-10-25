"""POST /v1/id/me/otp/enable/confirm: turn OTP login on."""

from app.interfaces.http.v1.id.account.schemas import CodeBody, UserMeResponse
from app.interfaces.http.v1.id.dependencies import ActorDep, AuthDep, CtxDep


async def post_otp_enable_confirm(
    body: CodeBody, actor: ActorDep, auth: AuthDep, ctx: CtxDep
) -> UserMeResponse:
    """Verify the code and return the updated account."""
    await auth.confirm_otp_enable.execute(actor, body.code, ctx)
    return UserMeResponse.of(await auth.get_me.execute(actor))
