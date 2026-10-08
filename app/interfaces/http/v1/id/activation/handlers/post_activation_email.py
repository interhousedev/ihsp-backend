"""POST /v1/id/activation/{token}/email: send the email confirmation code."""

from app.interfaces.http.v1.id.activation.schemas import ActivationEmailBody
from app.interfaces.http.v1.id.dependencies import AuthDep, CtxDep

from fastapi import Response


async def post_activation_email(
    token: str, body: ActivationEmailBody, auth: AuthDep, ctx: CtxDep
) -> Response:
    """Email a code to the address the staff member wants as recovery email."""
    await auth.activation_send_email_code.execute(token, str(body.email), ctx)
    return Response(status_code=202)
