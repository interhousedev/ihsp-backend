"""HTTP client for Ory Hydra's admin and public APIs."""

from typing import Any

from app.modules.identity.domain.errors import (
    ChallengeUsedError,
    HydraUnavailableError,
    InvalidChallengeError,
)
from app.modules.identity.ports.hydra_gateway import (
    ConsentRequest,
    HydraClient,
    LoginRequest,
    LogoutRequest,
    TokenSet,
)
from app.shared.base_error import UnauthorizedError

import httpx
import structlog

log = structlog.get_logger(__name__)

JWT_BEARER_GRANT = "urn:ietf:params:oauth:grant-type:jwt-bearer"
LOGIN_PATH = "/admin/oauth2/auth/requests/login"
CONSENT_PATH = "/admin/oauth2/auth/requests/consent"
LOGOUT_PATH = "/admin/oauth2/auth/requests/logout"


def _client(data: dict[str, Any]) -> HydraClient:
    return HydraClient(
        client_id=str(data.get("client_id", "")),
        client_name=str(data.get("client_name") or data.get("client_id", "")),
        metadata=dict(data.get("metadata") or {}),
        redirect_uris=tuple(data.get("redirect_uris") or ()),
    )


def _tokens(data: dict[str, Any]) -> TokenSet:
    return TokenSet(
        access_token=str(data["access_token"]),
        expires_in=int(data.get("expires_in", 0)),
        refresh_token=data.get("refresh_token"),
        id_token=data.get("id_token"),
        scope=str(data.get("scope", "")),
    )


class HydraAdmin:
    """Thin async wrapper over the Hydra endpoints identity needs."""

    def __init__(
        self,
        *,
        admin_url: str,
        public_url: str,
        miniapp_client_id: str = "miniapp",
        miniapp_client_secret: str = "",
        client: httpx.AsyncClient | None = None,
        timeout: float = 5.0,
    ) -> None:
        """Remember the base URLs; one shared connection pool serves both APIs."""
        self._admin = admin_url.rstrip("/")
        self._public = public_url.rstrip("/")
        self._miniapp_id = miniapp_client_id
        self._miniapp_secret = miniapp_client_secret
        self._http = client or httpx.AsyncClient(timeout=timeout)

    async def aclose(self) -> None:
        """Close the connection pool."""
        await self._http.aclose()

    # - - - Plumbing - - -

    async def _send(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        try:
            return await self._http.request(method, url, **kwargs)
        except httpx.HTTPError as exc:
            raise HydraUnavailableError(
                support_details=f"hydra {method} {url}: {exc!r}"
            ) from exc

    @staticmethod
    def _unexpected(response: httpx.Response) -> HydraUnavailableError:
        return HydraUnavailableError(
            support_details=(
                f"hydra {response.request.method} {response.request.url.path} "
                f"-> {response.status_code}: {response.text[:300]}"
            )
        )

    @staticmethod
    def _json(response: httpx.Response) -> dict[str, Any]:
        data = response.json()
        if not isinstance(data, dict):
            raise HydraUnavailableError(support_details="hydra returned non-object")
        return data

    async def _get_request(
        self, path: str, param: str, challenge: str
    ) -> dict[str, Any]:
        response = await self._send(
            "GET", f"{self._admin}{path}", params={param: challenge}
        )
        self._check_challenge(response)
        if response.status_code != 200:
            raise self._unexpected(response)
        return self._json(response)

    async def _put_request(
        self,
        path: str,
        param: str,
        challenge: str,
        body: dict[str, Any] | None = None,
    ) -> str:
        response = await self._send(
            "PUT", f"{self._admin}{path}", params={param: challenge}, json=body
        )
        self._check_challenge(response)
        if response.status_code != 200:
            raise self._unexpected(response)
        redirect: str = self._json(response)["redirect_to"]
        return redirect

    @staticmethod
    def _check_challenge(response: httpx.Response) -> None:
        if response.status_code == 410:
            redirect = response.json().get("redirect_to", "")
            raise ChallengeUsedError(params={"redirect_to": redirect})
        if response.status_code in (400, 404):
            raise InvalidChallengeError(support_details=response.text[:300])

    # - - - Login - - -

    async def get_login_request(self, challenge: str) -> LoginRequest:
        """Load a login request."""
        data = await self._get_request(LOGIN_PATH, "login_challenge", challenge)
        return LoginRequest(
            challenge=challenge,
            skip=bool(data.get("skip")),
            subject=data.get("subject") or None,
            client=_client(data.get("client") or {}),
            request_url=str(data.get("request_url", "")),
            requested_scope=tuple(data.get("requested_scope") or ()),
            requested_audience=tuple(data.get("requested_access_token_audience") or ()),
            session_id=data.get("session_id") or None,
        )

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
        """Accept a login."""
        body = {
            "subject": subject,
            "remember": remember,
            "remember_for": remember_for,
            "amr": amr,
            "context": context,
        }
        return await self._put_request(
            f"{LOGIN_PATH}/accept", "login_challenge", challenge, body
        )

    async def reject_login(self, challenge: str, error: str, description: str) -> str:
        """Reject a login."""
        body = {"error": error, "error_description": description}
        return await self._put_request(
            f"{LOGIN_PATH}/reject", "login_challenge", challenge, body
        )

    # - - - Consent - - -

    async def get_consent_request(self, challenge: str) -> ConsentRequest:
        """Load a consent request."""
        data = await self._get_request(CONSENT_PATH, "consent_challenge", challenge)
        return ConsentRequest(
            challenge=challenge,
            subject=str(data.get("subject", "")),
            client=_client(data.get("client") or {}),
            request_url=str(data.get("request_url", "")),
            requested_scope=tuple(data.get("requested_scope") or ()),
            requested_audience=tuple(data.get("requested_access_token_audience") or ()),
            context=dict(data.get("context") or {}),
            login_session_id=data.get("login_session_id") or None,
            skip=bool(data.get("skip")),
        )

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
        """Accept a consent with the claims for the tokens."""
        body = {
            "grant_scope": grant_scope,
            "grant_access_token_audience": grant_audience,
            "remember": remember,
            "remember_for": 0,
            "session": {
                "access_token": access_token_claims,
                "id_token": id_token_claims,
            },
        }
        return await self._put_request(
            f"{CONSENT_PATH}/accept", "consent_challenge", challenge, body
        )

    async def reject_consent(self, challenge: str, error: str, description: str) -> str:
        """Reject a consent."""
        body = {"error": error, "error_description": description}
        return await self._put_request(
            f"{CONSENT_PATH}/reject", "consent_challenge", challenge, body
        )

    # - - - Logout and sessions - - -

    async def get_logout_request(self, challenge: str) -> LogoutRequest:
        """Load a logout request."""
        data = await self._get_request(LOGOUT_PATH, "logout_challenge", challenge)
        return LogoutRequest(
            challenge=challenge,
            subject=data.get("subject") or None,
            sid=data.get("sid") or None,
        )

    async def accept_logout(self, challenge: str) -> str:
        """Accept a logout."""
        return await self._put_request(
            f"{LOGOUT_PATH}/accept", "logout_challenge", challenge
        )

    async def revoke_login_sessions(
        self, *, subject: str | None = None, sid: str | None = None
    ) -> None:
        """Delete login sessions (by subject or by sid)."""
        params = {k: v for k, v in {"subject": subject, "sid": sid}.items() if v}
        response = await self._send(
            "DELETE", f"{self._admin}/admin/oauth2/auth/sessions/login", params=params
        )
        if response.status_code not in (204, 404):
            raise self._unexpected(response)

    async def revoke_consent_sessions(
        self, subject: str, client_id: str | None = None
    ) -> None:
        """Delete consent sessions and their tokens."""
        params = {"subject": subject}
        params.update({"client": client_id} if client_id else {"all": "true"})
        response = await self._send(
            "DELETE",
            f"{self._admin}/admin/oauth2/auth/sessions/consent",
            params=params,
        )
        if response.status_code not in (204, 404):
            raise self._unexpected(response)

    # - - - Clients - - -

    async def list_clients(self) -> list[HydraClient]:
        """List OAuth clients."""
        response = await self._send(
            "GET", f"{self._admin}/admin/clients", params={"page_size": 500}
        )
        if response.status_code != 200:
            raise self._unexpected(response)
        data = response.json()
        return [_client(item) for item in data] if isinstance(data, list) else []

    async def get_client(self, client_id: str) -> HydraClient | None:
        """Return one client or None."""
        response = await self._send("GET", f"{self._admin}/admin/clients/{client_id}")
        if response.status_code == 404:
            return None
        if response.status_code != 200:
            raise self._unexpected(response)
        return _client(self._json(response))

    async def set_client_metadata(
        self, client_id: str, metadata: dict[str, Any]
    ) -> HydraClient:
        """Replace a client's metadata with a JSON patch."""
        patch = [{"op": "add", "path": "/metadata", "value": metadata}]
        response = await self._send(
            "PATCH", f"{self._admin}/admin/clients/{client_id}", json=patch
        )
        if response.status_code == 404:
            raise InvalidChallengeError(support_details=f"unknown client {client_id}")
        if response.status_code != 200:
            raise self._unexpected(response)
        return _client(self._json(response))

    # - - - Tokens (public API) - - -

    async def _token_request(
        self, data: dict[str, str], *, auth: tuple[str, str] | None = None
    ) -> TokenSet:
        response = await self._send(
            "POST", f"{self._public}/oauth2/token", data=data, auth=auth
        )
        if response.status_code >= 500:
            raise self._unexpected(response)
        if response.status_code != 200:
            body = response.json() if response.content else {}
            raise UnauthorizedError(
                support_details=f"hydra token error: {body.get('error', 'unknown')}"
            )
        return _tokens(self._json(response))

    async def exchange_code(
        self, client_id: str, code: str, verifier: str, redirect_uri: str
    ) -> TokenSet:
        """Exchange an authorization code with PKCE."""
        return await self._token_request(
            {
                "grant_type": "authorization_code",
                "client_id": client_id,
                "code": code,
                "code_verifier": verifier,
                "redirect_uri": redirect_uri,
            }
        )

    async def refresh(self, client_id: str, refresh_token: str) -> TokenSet:
        """Rotate a refresh token."""
        return await self._token_request(
            {
                "grant_type": "refresh_token",
                "client_id": client_id,
                "refresh_token": refresh_token,
            }
        )

    async def revoke_token(self, client_id: str, token: str) -> None:
        """Revoke a token (Hydra answers 200 even for unknown tokens)."""
        response = await self._send(
            "POST",
            f"{self._public}/oauth2/revoke",
            data={"token": token, "client_id": client_id},
        )
        if response.status_code >= 500:
            raise self._unexpected(response)

    async def introspect(self, token: str) -> dict[str, Any]:
        """Introspect a token through the admin API."""
        response = await self._send(
            "POST", f"{self._admin}/admin/oauth2/introspect", data={"token": token}
        )
        if response.status_code != 200:
            raise self._unexpected(response)
        return self._json(response)

    async def jwt_bearer(self, assertion: str, scope: str, audience: str) -> TokenSet:
        """Redeem a signed assertion with the confidential miniapp client."""
        return await self._token_request(
            {
                "grant_type": JWT_BEARER_GRANT,
                "assertion": assertion,
                "scope": scope,
                "audience": audience,
            },
            auth=(self._miniapp_id, self._miniapp_secret),
        )
