"""POST /v1/id/me/otp/disable: turn OTP login off."""

from app.interfaces.http.v1.id.account.schemas import OtpDisableBody, UserMeResponse
from app.interfaces.http.v1.id.dependencies import ActorDep, AuthDep, CtxDep


async def post_otp_disable(
    body: OtpDisableBody, actor: ActorDep, auth: AuthDep, ctx: CtxDep
) -> UserMeResponse:
    """Needs the password; refused for Administration."""
    await auth.disable_otp.execute(actor, body.password, ctx)
    return UserMeResponse.of(await auth.get_me.execute(actor))
