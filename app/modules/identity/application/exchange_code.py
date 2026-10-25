"""POST /v1/oauth/token: trade an authorization code for tokens."""

from dataclasses import dataclass

from app.modules.identity.application.token_grant import TokenGrant, require_web_client
from app.modules.identity.ports.hydra_gateway import HydraGateway


@dataclass(frozen=True, slots=True)
class ExchangeCode:
    """The browser never sees the refresh token; the handler puts it in a cookie."""

    hydra: HydraGateway

    async def execute(
        self, client_id: str, code: str, code_verifier: str, redirect_uri: str
    ) -> TokenGrant:
        """Redeem the code at Hydra (PKCE)."""
        require_web_client(client_id)
        tokens = await self.hydra.exchange_code(
            client_id, code, code_verifier, redirect_uri
        )
        return TokenGrant(
            access_token=tokens.access_token,
            expires_in=tokens.expires_in,
            refresh_token=tokens.refresh_token,
        )
