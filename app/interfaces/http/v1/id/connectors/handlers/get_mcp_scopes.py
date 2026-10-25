"""GET /v1/id/mcp-scopes: the scope catalog."""

from app.interfaces.http.v1.id.connectors.schemas import (
    ScopeCatalogResponse,
    ServerCatalogResponse,
)
from app.interfaces.http.v1.id.dependencies import AuthDep


async def get_mcp_scopes(auth: AuthDep) -> ScopeCatalogResponse:
    """Servers, scopes with their tools, and presets."""
    servers = auth.get_mcp_scopes.execute()
    return ScopeCatalogResponse(
        servers=[ServerCatalogResponse.of(server) for server in servers]
    )
