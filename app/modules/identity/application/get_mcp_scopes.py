"""GET /v1/id/mcp-scopes: the scope catalog the connector pages show."""

from dataclasses import dataclass

from app.modules.identity.domain.scopes import (
    ALLOWED_SERVER_ROLES,
    PRESETS,
    SCOPE_CATALOG,
    SERVERS,
    Preset,
    ScopeInfo,
)
from app.shared.actor import Role


@dataclass(frozen=True, slots=True)
class ServerCatalog:
    """One MCP server with its roles, scopes and presets."""

    server: str
    roles: list[Role]
    scopes: tuple[ScopeInfo, ...]
    presets: tuple[Preset, ...]


@dataclass(frozen=True, slots=True)
class GetMcpScopes:
    """Static data from spec MCP-8."""

    def execute(self) -> list[ServerCatalog]:
        """Return the catalog of all three servers."""
        return [
            ServerCatalog(
                server=server,
                roles=sorted(ALLOWED_SERVER_ROLES[server], key=lambda r: r.value),
                scopes=SCOPE_CATALOG[server],
                presets=PRESETS[server],
            )
            for server in SERVERS
        ]
