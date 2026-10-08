"""Verifies Hydra's JWT access tokens locally (signature, claims, epoch, revocation)."""

from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any
from uuid import UUID

from app.modules.identity.infrastructure.hydra.jwks import JwksCache
from app.modules.identity.ports.revocation_list import AuthEpochCache, RevocationList
from app.shared.actor import Actor, Role
from app.shared.base_error import UnauthorizedError
from app.shared.clock import Clock
from app.shared.contracts.auth import (
    AUDIENCE_MCP_ADMIN,
    AUDIENCE_MCP_LMS,
    AUDIENCE_MCP_STUDENT,
)

from joserfc import jwt
from joserfc.errors import InvalidKeyIdError, JoseError

ALGORITHMS = ["RS256", "ES256"]
MCP_AUDIENCES = frozenset({AUDIENCE_MCP_STUDENT, AUDIENCE_MCP_LMS, AUDIENCE_MCP_ADMIN})
EpochLoader = Callable[[UUID], Awaitable[int | None]]


def _unauthorized(reason: str) -> UnauthorizedError:
    return UnauthorizedError(support_details=f"access token: {reason}")


_ROLE_VALUES = {role.value for role in Role}


def _roles(raw: Any) -> frozenset[Role]:
    return frozenset(Role(item) for item in (raw or []) if item in _ROLE_VALUES)


def _token_scopes(claims: dict[str, Any]) -> frozenset[str]:
    """Granted scopes: `scp` array (Hydra default) or a space-separated `scope`."""
    scopes: set[str] = set()
    scp = claims.get("scp")
    if isinstance(scp, list):
        scopes.update(str(item) for item in scp)
    elif isinstance(scp, str):
        scopes.update(scp.split())
    scope = claims.get("scope")
    if isinstance(scope, str):
        scopes.update(scope.split())
    return frozenset(scopes)


def _datetime(raw: Any) -> datetime | None:
    if not isinstance(raw, str):
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _uuid(raw: Any, reason: str) -> UUID:
    try:
        return UUID(str(raw))
    except ValueError as exc:
        raise _unauthorized(reason) from exc


class HydraAccessTokenVerifier:
    """AccessTokenVerifier for audience ihsp-api and the three MCP audiences."""

    def __init__(
        self,
        *,
        jwks: JwksCache,
        issuer: str,
        epochs: AuthEpochCache,
        revocations: RevocationList,
        load_epoch: EpochLoader,
        clock: Clock,
    ) -> None:
        """Wire the key source, the epoch cache with its DB fallback, the clock."""
        self._jwks = jwks
        # Hydra signs `iss` exactly as configured; accept it with or without the
        # trailing slash so a deployment can switch without invalidating tokens.
        base = issuer.rstrip("/")
        self._issuers = [base, f"{base}/"]
        self._epochs = epochs
        self._revocations = revocations
        self._load_epoch = load_epoch
        self._clock = clock

    async def verify(self, token: str, *, audience: str) -> Actor:
        """Return the actor behind a valid token or raise UnauthorizedError."""
        claims = await self._decode(token, audience)
        ext: dict[str, Any] = claims.get("ext") or {}
        user_id = _uuid(claims.get("sub"), "bad sub")
        await self._check_epoch(user_id, ext.get("auth_epoch"))
        sid = str(ext.get("sid") or "")
        if not sid:
            raise _unauthorized("no sid")
        if await self._revocations.is_revoked(sid):
            raise _unauthorized("revoked")
        return self._actor(user_id, claims, ext, sid, audience)

    async def _decode_token(self, token: str) -> jwt.Token:
        """Verify the signature; refetch the JWKS once for an unknown key id."""
        for force in (False, True):
            keys = await self._jwks.key_set(force=force)
            try:
                return jwt.decode(token, keys, algorithms=ALGORITHMS)
            except InvalidKeyIdError:
                continue
            except JoseError as exc:
                raise _unauthorized(f"invalid ({exc.__class__.__name__})") from exc
        raise _unauthorized("unknown key id")

    async def _decode(self, token: str, audience: str) -> dict[str, Any]:
        decoded = await self._decode_token(token)
        registry = jwt.JWTClaimsRegistry(
            now=lambda: int(self._clock.now().timestamp()),
            iss={"essential": True, "values": self._issuers},
            aud={"essential": True, "value": audience},
            exp={"essential": True},
            sub={"essential": True},
        )
        try:
            registry.validate(decoded.claims)
        except JoseError as exc:
            raise _unauthorized(f"claims ({exc.__class__.__name__})") from exc
        return dict(decoded.claims)

    async def _check_epoch(self, user_id: UUID, token_epoch: Any) -> None:
        if not isinstance(token_epoch, int):
            raise _unauthorized("no auth_epoch")
        current = await self._epochs.get(user_id)
        if current == token_epoch:
            return
        current = await self._load_epoch(user_id)
        if current is None:
            raise _unauthorized("unknown user")
        await self._epochs.set(user_id, current)
        if current != token_epoch:
            raise _unauthorized("stale auth_epoch")

    def _actor(
        self,
        user_id: UUID,
        claims: dict[str, Any],
        ext: dict[str, Any],
        sid: str,
        audience: str,
    ) -> Actor:
        connector_raw = ext.get("connector_id")
        connector_id = (
            _uuid(connector_raw, "bad connector_id") if connector_raw else None
        )
        # MCP servers need the granted scopes of OAuth tokens (README MCP-5).
        scopes = _token_scopes(claims) if audience in MCP_AUDIENCES else frozenset()
        return Actor(
            user_id=user_id,
            roles=_roles(ext.get("roles")),
            session_id=None if connector_id else _uuid(sid, "bad sid"),
            connector_id=connector_id,
            client_id=claims.get("client_id"),
            amr=frozenset(str(a) for a in ext.get("amr") or []),
            mfa_at=_datetime(ext.get("mfa_at")),
            scopes=scopes,
        )
