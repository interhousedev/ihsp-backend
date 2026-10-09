"""Result of a token exchange: what the token handler hands to the browser."""

from dataclasses import dataclass

from app.modules.identity.domain.client_policy import WEB_CLIENTS
from app.modules.identity.domain.errors import UnknownClientError


@dataclass(frozen=True, slots=True)
class TokenGrant:
    """The access token for the body and the refresh token for the cookie."""

    access_token: str
    expires_in: int
    refresh_token: str | None = None


def require_web_client(client_id: str) -> str:
    """Only our first-party web clients use the token handler."""
    if client_id not in WEB_CLIENTS:
        raise UnknownClientError(params={"client_id": client_id})
    return client_id
