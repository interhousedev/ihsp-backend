"""An in-memory Hydra that records every call."""

from typing import Any

from app.modules.identity.domain.errors import ChallengeUsedError
from app.modules.identity.ports.hydra_gateway import (
    ConsentRequest,
    HydraClient,
    LoginRequest,
    LogoutRequest,
    TokenSet,
)

FIRST_PARTY = ("id", "sp", "staff", "admin", "lms")


def client(client_id: str, **metadata: Any) -> HydraClient:
    """A Hydra client with a readable name."""
    return HydraClient(
        client_id=client_id,
        client_name=f"Client {client_id}",
        metadata=metadata,
        redirect_uris=("https://app.example.org/callback",),
    )


class FakeHydra:
    """Implements HydraGateway; tests register requests and read `calls`."""

    def __init__(self) -> None:
        """Start with the five first-party clients and no requests."""
        self.clients: dict[str, HydraClient] = {c: client(c) for c in FIRST_PARTY}
        self.login_requests: dict[str, LoginRequest] = {}
        self.consent_requests: dict[str, ConsentRequest] = {}
        self.logout_requests: dict[str, LogoutRequest] = {}
        self.used: set[str] = set()
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.tokens = TokenSet(
            access_token="access.jwt.token", expires_in=600, refresh_token="refresh-1"
        )
        self.introspection: dict[str, Any] = {"active": False}

    # - - - Test helpers - - -

    def add_login(self, challenge: str = "lc-1", **kwargs: Any) -> LoginRequest:
        """Register a login request (default: client sp, no skip)."""
        client_id = kwargs.pop("client_id", "sp")
        request = LoginRequest(
            challenge=challenge,
            skip=kwargs.pop("skip", False),
            subject=kwargs.pop("subject", None),
            client=self.clients.setdefault(client_id, client(client_id)),
            request_url=kwargs.pop("request_url", "https://hydra/oauth2/auth?x=1"),
            session_id=kwargs.pop("session_id", f"hydra-sid-{challenge}"),
            **kwargs,
        )
        self.login_requests[challenge] = request
        return request

    def add_consent(
        self, challenge: str = "cc-1", *, client_id: str = "sp", **kwargs: Any
    ) -> ConsentRequest:
        """Register a consent request."""
        kwargs.setdefault("request_url", "https://hydra/oauth2/auth?x=1")
        request = ConsentRequest(
            challenge=challenge,
            client=self.clients.setdefault(client_id, client(client_id)),
            **kwargs,
        )
        self.consent_requests[challenge] = request
        return request

    def names(self) -> list[str]:
        """Names of the calls made so far."""
        return [name for name, _ in self.calls]

    def last(self, name: str) -> dict[str, Any]:
        """Arguments of the latest call with this name."""
        return next(args for call, args in reversed(self.calls) if call == name)

    def _record(self, name: str, **args: Any) -> None:
        self.calls.append((name, args))

    def _check(self, challenge: str) -> None:
        if challenge in self.used:
            raise ChallengeUsedError(params={"redirect_to": "https://hydra/restart"})

    # - - - Login - - -

    async def get_login_request(self, challenge: str) -> LoginRequest:
        """Return the registered request."""
        self._check(challenge)
        return self.login_requests[challenge]

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
        """Record the acceptance."""
        self._record(
            "accept_login",
            challenge=challenge,
            subject=subject,
            remember=remember,
            remember_for=remember_for,
            amr=amr,
            context=context,
        )
        return f"https://hydra/continue?login_verifier={challenge}"

    async def reject_login(self, challenge: str, error: str, description: str) -> str:
        """Record the rejection."""
        self._record("reject_login", challenge=challenge, error=error)
        return f"https://hydra/rejected?challenge={challenge}"

    # - - - Consent - - -

    async def get_consent_request(self, challenge: str) -> ConsentRequest:
        """Return the registered request."""
        self._check(challenge)
        return self.consent_requests[challenge]

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
        """Record the acceptance."""
        self._record(
            "accept_consent",
            challenge=challenge,
            grant_scope=grant_scope,
            grant_audience=grant_audience,
            access_token_claims=access_token_claims,
            id_token_claims=id_token_claims,
        )
        return f"https://hydra/code?consent_verifier={challenge}"

    async def reject_consent(self, challenge: str, error: str, description: str) -> str:
        """Record the rejection."""
        self._record("reject_consent", challenge=challenge, error=error)
        return f"https://hydra/denied?challenge={challenge}"

    # - - - Logout and sessions - - -

    async def get_logout_request(self, challenge: str) -> LogoutRequest:
        """Return the registered request."""
        return self.logout_requests[challenge]

    async def accept_logout(self, challenge: str) -> str:
        """Record the acceptance."""
        self._record("accept_logout", challenge=challenge)
        return "https://hydra/after-logout"

    async def revoke_login_sessions(
        self, *, subject: str | None = None, sid: str | None = None
    ) -> None:
        """Record the revocation."""
        self._record("revoke_login_sessions", subject=subject, sid=sid)

    async def revoke_consent_sessions(
        self, subject: str, client_id: str | None = None
    ) -> None:
        """Record the revocation."""
        self._record("revoke_consent_sessions", subject=subject, client_id=client_id)

    # - - - Clients - - -

    async def list_clients(self) -> list[HydraClient]:
        """All clients."""
        return list(self.clients.values())

    async def get_client(self, client_id: str) -> HydraClient | None:
        """One client or None."""
        return self.clients.get(client_id)

    async def set_client_metadata(
        self, client_id: str, metadata: dict[str, Any]
    ) -> HydraClient:
        """Replace the metadata."""
        self._record("set_client_metadata", client_id=client_id, metadata=metadata)
        old = self.clients[client_id]
        new = HydraClient(
            client_id=old.client_id,
            client_name=old.client_name,
            metadata=metadata,
            redirect_uris=old.redirect_uris,
        )
        self.clients[client_id] = new
        return new

    # - - - Tokens - - -

    async def exchange_code(
        self, client_id: str, code: str, verifier: str, redirect_uri: str
    ) -> TokenSet:
        """Record and return the canned tokens."""
        self._record(
            "exchange_code",
            client_id=client_id,
            code=code,
            verifier=verifier,
            redirect_uri=redirect_uri,
        )
        return self.tokens

    async def refresh(self, client_id: str, refresh_token: str) -> TokenSet:
        """Record and return the canned tokens."""
        self._record("refresh", client_id=client_id, refresh_token=refresh_token)
        return self.tokens

    async def revoke_token(self, client_id: str, token: str) -> None:
        """Record the revocation."""
        self._record("revoke_token", client_id=client_id, token=token)

    async def introspect(self, token: str) -> dict[str, Any]:
        """Return the canned introspection."""
        self._record("introspect", token=token)
        return self.introspection

    async def jwt_bearer(self, assertion: str, scope: str, audience: str) -> TokenSet:
        """Record and return the canned tokens (without a refresh token)."""
        self._record("jwt_bearer", assertion=assertion, scope=scope, audience=audience)
        return TokenSet(access_token="tg.access.token", expires_in=600)
