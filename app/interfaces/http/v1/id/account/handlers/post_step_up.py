"""POST /v1/id/me/step-up: send a code for a sensitive action."""

from app.interfaces.http.v1.id.dependencies import ActorDep, AuthDep, CtxDep

from fastapi import Response


async def post_step_up(actor: ActorDep, auth: AuthDep, ctx: CtxDep) -> Response:
    """Send the code to the caller's channels."""
    await auth.step_up.execute(actor, ctx)
    return Response(status_code=202)
