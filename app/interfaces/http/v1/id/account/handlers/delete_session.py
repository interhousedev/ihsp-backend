"""DELETE /v1/id/me/sessions/{id}: log out one device."""

from uuid import UUID

from app.interfaces.http.v1.id.dependencies import ActorDep, AuthDep, CtxDep

from fastapi import Response


async def delete_session(
    id: UUID, actor: ActorDep, auth: AuthDep, ctx: CtxDep
) -> Response:
    """Revoke the session."""
    await auth.revoke_session.execute(actor, id, ctx)
    return Response(status_code=204)
