"""POST /v1/id/me/email/change: password, then a code to the new address."""

from app.interfaces.http.v1.id.account.schemas import EmailChangeBody
from app.interfaces.http.v1.id.dependencies import ActorDep, AuthDep, CtxDep

from fastapi import Response


async def post_email_change(
    body: EmailChangeBody, actor: ActorDep, auth: AuthDep, ctx: CtxDep
) -> Response:
    """Start the recovery email change."""
    await auth.request_email_change.execute(
        actor, body.password, str(body.new_email), ctx
    )
    return Response(status_code=202)
