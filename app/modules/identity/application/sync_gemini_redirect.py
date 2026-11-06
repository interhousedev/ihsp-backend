"""Teach a Gemini client the redirect URI Google generates per user and connector.

Gemini sends ``.../r/user_bound_custom-mcp-<account>-<name>``, which cannot be known
when the client is created, and Hydra only compares exact URIs. Anyone may already
self-register a client with such a Google-hosted URI, so adding one gives no new power:
the callback is still only Google's, and consent still belongs to the user.
"""

from dataclasses import dataclass

from app.modules.identity.domain.mcp_clients import (
    is_gemini_cli_redirect,
    service_of_redirect,
)
from app.modules.identity.ports.hydra_gateway import HydraGateway

MAX_REDIRECTS_PER_CLIENT = 50


@dataclass(frozen=True, slots=True)
class SyncGeminiRedirect:
    """Add a hosted Gemini redirect URI to a Gemini client just before authorization."""

    hydra: HydraGateway

    async def execute(self, client_id: str, redirect_uri: str) -> bool:
        """Return True when the URI was added; Hydra judges everything else."""
        if (
            service_of_redirect(redirect_uri) != "gemini"
            or is_gemini_cli_redirect(redirect_uri)
            or len(client_id) > 128
        ):
            return False
        client = await self.hydra.get_client(client_id)
        if client is None or client.metadata.get("service") != "gemini":
            return False
        uris = list(client.redirect_uris)
        if redirect_uri in uris or len(uris) >= MAX_REDIRECTS_PER_CLIENT:
            return False
        await self.hydra.set_client_redirects(client_id, [*uris, redirect_uri])
        return True
