"""POST /v1/id/consent/otp: send the step-up code for an Administration consent."""

from app.interfaces.http.v1.id.dependencies import AuthDep, CtxDep
from app.interfaces.http.v1.id.login.schemas import ConsentOtpBody

from fastapi import Response


async def post_consent_otp(
    body: ConsentOtpBody, auth: AuthDep, ctx: CtxDep
) -> Response:
    """The consent page has no bearer token; the challenge names the user."""
    await auth.send_consent_otp.execute(body.consent_challenge, ctx)
    return Response(status_code=202)
