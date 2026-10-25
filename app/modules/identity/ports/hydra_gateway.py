"""Port: Ory Hydra admin and public APIs."""

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class HydraClient:
    """An OAuth client registered in Hydra (secret never included)."""

    client_id: str
    client_name: str
    metadata: dict[str, Any] = field(default_factory=dict)
    redirect_uris: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class LoginRequest:
    """Hydra's login request."""

    challenge: str
    skip: bool
    subject: str | None
    client: HydraClient
    request_url: str
    requested_scope: tuple[str, ...] = ()
    requested_audience: tuple[str, ...] = ()
    session_id: str | None = None


@dataclass(frozen=True, slots=True)
class ConsentRequest:
    """Hydra's consent request."""

    challenge: str
    subject: str
    client: HydraClient
    request_url: str
    requested_scope: tuple[str, ...] = ()
    requested_audience: tuple[str, ...] = ()
    context: dict[str, Any] = field(default_factory=dict)
    login_session_id: str | None = None
    skip: bool = False


@dataclass(frozen=True, slots=True)
class LogoutRequest:
    """Hydra's logout request."""

    challenge: str
    subject: str | None
    sid: str | None


@dataclass(frozen=True, slots=True)
class TokenSet:
    """Tokens returned by Hydra's token endpoint."""

    access_token: str
    expires_in: int
    refresh_token: str | None = None
    id_token: str | None = None
    scope: str = ""


class HydraGateway(Protocol):
    """The calls identity makes to Hydra."""

    async def get_login_request(self, challenge: str) -> LoginRequest:
        """Load a login request (ChallengeUsedError on 410)."""
        ...

    async def accept_login(
        self,
        challenge: str,
        *,
        subject: str,
        remember: bool,
        remember_for: int,
        amr: list[str],
        context: dict[str, Any],
    ) -> str:
        """Accept the login; return the URL to send the browser to."""
        ...

    async def reject_login(self, challenge: str, error: str, description: str) -> str:
        """Reject the login; return the redirect URL."""
        ...

    async def get_consent_request(self, challenge: str) -> ConsentRequest:
        """Load a consent request."""
        ...

    async def accept_consent(
        self,
        challenge: str,
        *,
        grant_scope: list[str],
        grant_audience: list[str],
        remember: bool,
        access_token_claims: dict[str, Any],
        id_token_claims: dict[str, Any],
    ) -> str:
        """Accept the consent with claims; return the redirect URL."""
        ...

    async def reject_consent(self, challenge: str, error: str, description: str) -> str:
        """Reject the consent; return the redirect URL."""
        ...

    async def get_logout_request(self, challenge: str) -> LogoutRequest:
        """Load a logout request."""
        ...

    async def accept_logout(self, challenge: str) -> str:
        """Accept the logout; return the redirect URL."""
        ...

    async def revoke_login_sessions(
        self, *, subject: str | None = None, sid: str | None = None
    ) -> None:
        """Delete Hydra's login sessions of a subject or one sid."""
        ...

    async def revoke_consent_sessions(
        self, subject: str, client_id: str | None = None
    ) -> None:
        """Delete consent sessions (and their tokens) of a subject."""
        ...

    async def list_clients(self) -> list[HydraClient]:
        """List registered OAuth clients."""
        ...

    async def get_client(self, client_id: str) -> HydraClient | None:
        """Return one client or None."""
        ...

    async def set_client_metadata(
        self, client_id: str, metadata: dict[str, Any]
    ) -> HydraClient:
        """Replace the client's metadata."""
        ...

    async def exchange_code(
        self, client_id: str, code: str, verifier: str, redirect_uri: str
    ) -> TokenSet:
        """Exchange an authorization code (PKCE)."""
        ...

    async def refresh(self, client_id: str, refresh_token: str) -> TokenSet:
        """Rotate a refresh token."""
        ...

    async def revoke_token(self, client_id: str, token: str) -> None:
        """Revoke an access or refresh token."""
        ...

    async def introspect(self, token: str) -> dict[str, Any]:
        """Introspect a token (admin API)."""
        ...

    async def jwt_bearer(self, assertion: str, scope: str, audience: str) -> TokenSet:
        """Redeem a signed assertion at the token endpoint (RFC 7523)."""
        ...
