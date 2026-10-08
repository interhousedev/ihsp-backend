"""POST /v1/oauth/token-hook: Hydra asks before issuing any token (hydra.md 4)."""

from dataclasses import dataclass
from typing import Any, Literal

from app.modules.identity.application.consent_support import (
    access_claims,
    parse_datetime,
    parse_uuid,
)
from app.modules.identity.domain.scopes import role_may_use_server
from app.modules.identity.domain.user import User
from app.modules.identity.ports.assertion_signer import AssertionSigner
from app.modules.identity.ports.unit_of_work import IdentityUnitOfWorkPort, UowFactory
from app.shared.clock import Clock

JWT_BEARER_GRANT = "urn:ietf:params:oauth:grant-type:jwt-bearer"


@dataclass(frozen=True, slots=True)
class HookResult:
    """What to answer Hydra: full claims (200), deny (403) or leave as is (204)."""

    action: Literal["claims", "deny", "unchanged"]
    session: dict[str, Any] | None = None


DENY = HookResult("deny")


@dataclass(frozen=True, slots=True)
class HandleTokenHook:
    """Refuses tokens for blocked users and revoked sessions; refreshes the claims."""

    uow_factory: UowFactory
    signer: AssertionSigner
    clock: Clock

    async def execute(self, payload: dict[str, Any]) -> HookResult:
        """Decide for one token request."""
        session = payload.get("session") or {}
        id_token = session.get("id_token") or {}
        subject = id_token.get("subject") or (
            id_token.get("id_token_claims") or {}
        ).get("sub")
        if not subject:
            return HookResult("unchanged")
        user_id = parse_uuid(subject)
        if user_id is None:
            return DENY
        request = payload.get("request") or {}
        origin = self._origin(request, session.get("extra") or {}, user_id)
        if origin is None:
            return DENY
        async with self.uow_factory() as uow:
            user = await uow.users.get(user_id)
            if user is None or not user.is_active:
                return DENY
            return await self._claims(uow, user, origin)

    def _origin(
        self, request: dict[str, Any], extra: dict[str, Any], user_id: Any
    ) -> dict[str, Any] | None:
        """Where sid, amr and mfa_at come from: our assertion or the consent session."""
        if JWT_BEARER_GRANT in (request.get("grant_types") or []):
            assertions = (request.get("payload") or {}).get("assertion") or []
            claims = self.signer.read(assertions[0]) if assertions else None
            if claims is None or claims.user_id != user_id:
                return None
            return {"sid": str(claims.session_id), "amr": list(claims.amr)}
        return extra or None

    async def _claims(
        self, uow: IdentityUnitOfWorkPort, user: User, origin: dict[str, Any]
    ) -> HookResult:
        now = self.clock.now()
        connector_id = parse_uuid(origin.get("connector_id"))
        extra: dict[str, Any] = {}
        if connector_id is not None:
            connector = await uow.connectors.get(connector_id)
            if (
                connector is None
                or connector.user_id != user.id
                or not connector.is_active(now)
                or not role_may_use_server(user.roles, connector.server)
            ):
                return DENY
            sid = str(connector.id)
            extra = {"connector_id": sid, "server": connector.server}
        else:
            session_id = parse_uuid(origin.get("sid"))
            session = await uow.sessions.get(session_id) if session_id else None
            if session is None or session.user_id != user.id:
                return DENY
            if not session.is_active(now):
                return DENY
            sid = str(session.id)
        mfa = parse_datetime(origin.get("mfa_at"))
        claims = access_claims(
            user,
            sid=sid,
            amr=[str(a) for a in origin.get("amr") or []],
            mfa_at=mfa.isoformat() if mfa else None,
            extra=extra,
        )
        return HookResult(
            "claims",
            {"access_token": claims, "id_token": {"roles": claims["roles"]}},
        )
