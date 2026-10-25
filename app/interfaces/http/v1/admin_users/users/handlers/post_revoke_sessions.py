"""POST /v1/admin/users/{id}/sessions/revoke."""

from uuid import UUID

from app.interfaces.http.v1.id.dependencies import AdminDep, AuthDep, CtxDep

from fastapi import Response


async def post_revoke_sessions(
    id: UUID, admin: AdminDep, auth: AuthDep, ctx: CtxDep
) -> Response:
    """Revoke every session of the user."""
    await auth.revoke_user_sessions.execute(admin, id, ctx)
    return Response(status_code=204)
