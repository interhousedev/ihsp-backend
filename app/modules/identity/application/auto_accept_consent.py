"""First-party clients never see a consent screen: accept with the session's claims."""

from dataclasses import dataclass
from typing import Any

from app.modules.identity.application.consent_support import (
    access_claims,
    parse_uuid,
)
from app.modules.identity.domain.client_policy import may_use_client
from app.modules.identity.ports.hydra_gateway import ConsentRequest, HydraGateway
from app.modules.identity.ports.unit_of_work import UowFactory
from app.shared.clock import Clock
from app.shared.contracts.auth import AUDIENCE_API


@dataclass(frozen=True, slots=True)
class AutoAcceptConsent:
    """Accepts (or rejects) the consent of a first-party client."""

    uow_factory: UowFactory
    hydra: HydraGateway
    clock: Clock

    async def execute(self, request: ConsentRequest) -> str:
        """Return the redirect URL: the code, or an access_denied error."""
        claims = await self._claims(request)
        if claims is None:
            return await self.hydra.reject_consent(
                request.challenge, "access_denied", "account or session is not valid"
            )
        roles: list[str] = claims["roles"]
        return await self.hydra.accept_consent(
            request.challenge,
            grant_scope=list(request.requested_scope),
            grant_audience=[AUDIENCE_API],
            remember=False,
            access_token_claims=claims,
            id_token_claims={"roles": roles},
        )

    async def _claims(self, request: ConsentRequest) -> dict[str, Any] | None:
        user_id = parse_uuid(request.subject)
        session_id = parse_uuid(request.context.get("session_id"))
        if user_id is None or session_id is None:
            return None
        async with self.uow_factory() as uow:
            user = await uow.users.get(user_id)
            session = await uow.sessions.get(session_id)
        now = self.clock.now()
        if user is None or not user.is_active:
            return None
        if not may_use_client(request.client.client_id, user.roles):
            return None
        if session is None or session.user_id != user_id or not session.is_active(now):
            return None
        mfa_at = session.mfa_at.isoformat() if session.mfa_at else None
        return access_claims(
            user, sid=str(session.id), amr=list(session.amr), mfa_at=mfa_at
        )
