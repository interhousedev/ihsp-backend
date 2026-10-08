"""POST /v1/admin/oauth-clients/{client_id}/verify."""

from app.interfaces.http.v1.admin_users.oauth_clients.schemas import (
    OAuthClientResponse,
    VerifyBody,
)
from app.interfaces.http.v1.id.dependencies import AdminDep, AuthDep, CtxDep


async def post_verify(
    client_id: str, body: VerifyBody, admin: AdminDep, auth: AuthDep, ctx: CtxDep
) -> OAuthClientResponse:
    """Mark the client verified (or not)."""
    view = await auth.verify_oauth_client.execute(
        admin, client_id, verified=body.verified, ctx=ctx
    )
    return OAuthClientResponse.of(view)
