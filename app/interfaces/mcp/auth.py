"""Bearer token verification for the MCP servers (connector tokens and OAuth)."""

from app.interfaces.mcp.constants import (
    ALLOWED_ROLES_BY_SERVER,
    AUDIENCE_BY_SERVER,
    CONNECTOR_TOKEN_PREFIX,
    ServerName,
)
from app.shared.actor import Actor
from app.shared.base_error import BaseError
from app.shared.contracts.auth import AccessTokenVerifier, ConnectorTokenVerifier

import structlog
from mcp.server.auth.provider import AccessToken
from pydantic import ConfigDict

log = structlog.get_logger(__name__)


class IhspAccessToken(AccessToken):
    """SDK access token that also carries the IHSP actor for the tools."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    actor: Actor


class IhspTokenVerifier:
    """SDK `TokenVerifier` for one MCP server.

    Tokens starting with `ihsp_mcp_` are connector tokens; everything else is a
    Hydra access token whose audience must be this server's (`mcp-<server>`).
    A token that fails any check gives None, which the SDK answers with 401 and the
    `resource_metadata` link.
    """

    def __init__(
        self,
        *,
        server: ServerName,
        resource_url: str,
        access: AccessTokenVerifier,
        connector: ConnectorTokenVerifier,
    ) -> None:
        """Remember the server, its public URL and the two identity verifiers."""
        self.server = server
        self.resource_url = resource_url
        self._access = access
        self._connector = connector

    async def verify_token(self, token: str) -> AccessToken | None:
        """Return the access token for a valid bearer token, else None."""
        try:
            actor = await self._authenticate(token)
        except BaseError as error:
            log.info("mcp.token_rejected", server=self.server, code=error.code)
            return None
        if not actor.roles & ALLOWED_ROLES_BY_SERVER[self.server]:
            log.info("mcp.token_rejected", server=self.server, code="role-missing")
            return None
        return IhspAccessToken(
            token="",  # the raw secret is never kept after verification
            client_id=_client_id(actor),
            scopes=sorted(actor.scopes),
            resource=self.resource_url,
            subject=str(actor.user_id),
            claims={"server": self.server},
            actor=actor,
        )

    async def _authenticate(self, token: str) -> Actor:
        if token.startswith(CONNECTOR_TOKEN_PREFIX):
            return await self._connector.verify_connector(token, server=self.server)
        return await self._access.verify(
            token, audience=AUDIENCE_BY_SERVER[self.server]
        )


def _client_id(actor: Actor) -> str:
    if actor.connector_id is not None:
        return f"connector:{actor.connector_id}"
    return actor.client_id or "oauth"
