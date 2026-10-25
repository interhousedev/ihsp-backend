"""Auth contracts (provider: identity module; consumers: HTTP dependencies, MCP)."""

from typing import Literal, Protocol

from app.shared.actor import Actor

AUDIENCE_API = "ihsp-api"
AUDIENCE_MCP_STUDENT = "mcp-student"
AUDIENCE_MCP_LMS = "mcp-lms"
AUDIENCE_MCP_ADMIN = "mcp-admin"


class AccessTokenVerifier(Protocol):
    """Verifies access tokens issued through Hydra."""

    async def verify(self, token: str, *, audience: str) -> Actor:
        """Return the actor; raise UnauthorizedError for a bad token."""
        ...


class ConnectorTokenVerifier(Protocol):
    """Verifies MCP connector tokens."""

    async def verify_connector(
        self, token: str, *, server: Literal["student", "lms", "admin"]
    ) -> Actor:
        """Return the actor with connector_id and scopes set."""
        ...
