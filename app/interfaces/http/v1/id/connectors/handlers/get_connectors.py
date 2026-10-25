"""GET /v1/id/me/connectors: the caller's MCP connectors."""

from app.interfaces.http.v1.id.connectors.schemas import ConnectorResponse
from app.interfaces.http.v1.id.dependencies import ActorDep, AuthDep


async def get_connectors(actor: ActorDep, auth: AuthDep) -> list[ConnectorResponse]:
    """Newest first, revoked ones included."""
    connectors = await auth.list_connectors.execute(actor)
    return [ConnectorResponse.of(connector) for connector in connectors]
