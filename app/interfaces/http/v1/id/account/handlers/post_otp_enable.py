"""POST /v1/id/me/otp/enable: send a test code."""

from app.interfaces.http.v1.id.account.schemas import OtpEnableBody
from app.interfaces.http.v1.id.dependencies import ActorDep, AuthDep, CtxDep

from fastapi import Response


async def post_otp_enable(
    body: OtpEnableBody, actor: ActorDep, auth: AuthDep, ctx: CtxDep
) -> Response:
    """Send the code to the chosen channels."""
    await auth.enable_otp.execute(actor, via_email=body.via_email, ctx=ctx)
    return Response(status_code=202)
