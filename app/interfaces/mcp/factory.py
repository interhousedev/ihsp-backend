"""Construction of one FastMCP server with IHSP authentication."""

from app.interfaces.mcp.auth import IhspTokenVerifier
from app.interfaces.mcp.constants import ServerName
from app.interfaces.mcp.deps import McpDeps
from app.interfaces.mcp.endpoints import resource_url, transport_security
from app.interfaces.mcp.guard import ToolGuard
from app.interfaces.mcp.toolkit import ToolKit

from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP
from pydantic import AnyHttpUrl


def make_toolkit(
    deps: McpDeps, server: ServerName, *, title: str, instructions_key: str
) -> ToolKit:
    """Create the FastMCP server for `server` and the kit its tools register on.

    The server is stateless with JSON responses and serves its endpoint at `/` of
    its mount. Token audience is checked by `IhspTokenVerifier` (Hydra does not
    support RFC 8707 `resource`), so `validate_token_resource` stays off.
    """
    url = resource_url(deps.settings, server)
    verifier = IhspTokenVerifier(
        server=server,
        resource_url=url,
        access=deps.access_verifier,
        connector=deps.connector_verifier,
    )
    mcp = FastMCP(
        title,
        instructions=deps.t(instructions_key),
        stateless_http=True,
        json_response=True,
        streamable_http_path="/",
        transport_security=transport_security(deps.settings),
        token_verifier=verifier,
        auth=AuthSettings(
            issuer_url=AnyHttpUrl(deps.settings.hydra.issuer),
            resource_server_url=AnyHttpUrl(url),
            required_scopes=None,
            validate_token_resource=False,
        ),
    )
    return ToolKit(mcp=mcp, deps=deps, guard=ToolGuard(deps, server))
