"""Construction of one FastMCP server with IHSP authentication."""

from app.interfaces.mcp.auth import IhspTokenVerifier
from app.interfaces.mcp.catalog import CatalogMcp, enable_catalog
from app.interfaces.mcp.constants import ServerName, SourceServerName
from app.interfaces.mcp.deps import McpDeps
from app.interfaces.mcp.endpoints import resource_url, transport_security
from app.interfaces.mcp.guard import ToolGuard
from app.interfaces.mcp.toolkit import ToolKit

from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP
from pydantic import AnyHttpUrl


def make_mcp(
    deps: McpDeps,
    server: ServerName,
    *,
    title: str,
    instructions_key: str,
    cls: type[FastMCP] = FastMCP,
) -> FastMCP:
    """Create the authenticated FastMCP server for `server` (no tools yet).

    A `CatalogMcp` class also gets the instructions of the tool catalog appended.
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
    instructions = deps.t(instructions_key)
    if issubclass(cls, CatalogMcp):
        instructions = f"{instructions} {deps.t('mcp-instructions-catalog')}"
    return cls(
        title,
        instructions=instructions,
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


def make_toolkit(
    deps: McpDeps,
    server: ServerName,
    *,
    title: str,
    instructions_key: str,
    cls: type[FastMCP] = FastMCP,
) -> ToolKit:
    """Create the FastMCP server for `server` and the kit its tools register on."""
    mcp = make_mcp(
        deps, server, title=title, instructions_key=instructions_key, cls=cls
    )
    return ToolKit(mcp=mcp, deps=deps, guard=ToolGuard(deps, server))


def finish_catalog(kit: ToolKit, source: SourceServerName, pinned: list[str]) -> None:
    """Switch a role server to the small tool list once its tools are registered."""
    assert isinstance(kit.mcp, CatalogMcp)
    enable_catalog(kit.mcp, dict.fromkeys(kit.guard.registered, source), pinned)
