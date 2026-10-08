"""DELETE /v1/id/me/connectors/{id}: revoke a connector."""

from uuid import UUID

from app.interfaces.http.v1.id.dependencies import ActorDep, AuthDep, CtxDep

from fastapi import Response


async def delete_connector(
    id: UUID, actor: ActorDep, auth: AuthDep, ctx: CtxDep
) -> Response:
    """Revoke at once."""
    await auth.revoke_connector.execute(actor, id, ctx)
    return Response(status_code=204)
