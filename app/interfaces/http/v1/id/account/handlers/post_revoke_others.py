"""POST /v1/id/me/sessions/revoke-others: log out everywhere else."""

from app.interfaces.http.v1.id.dependencies import ActorDep, AuthDep, CtxDep

from fastapi import Response


async def post_revoke_others(actor: ActorDep, auth: AuthDep, ctx: CtxDep) -> Response:
    """Revoke every session except the current one."""
    await auth.revoke_other_sessions.execute(actor, ctx)
    return Response(status_code=204)
