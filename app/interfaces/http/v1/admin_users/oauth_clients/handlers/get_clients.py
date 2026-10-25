"""GET /v1/admin/oauth-clients."""

from app.interfaces.http.v1.admin_users.oauth_clients.schemas import OAuthClientResponse
from app.interfaces.http.v1.id.dependencies import AdminDep, AuthDep


async def get_clients(_admin: AdminDep, auth: AuthDep) -> list[OAuthClientResponse]:
    """MCP clients that registered themselves in Hydra."""
    views = await auth.list_oauth_clients.execute()
    return [OAuthClientResponse.of(view) for view in views]
