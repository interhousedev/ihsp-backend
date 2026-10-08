"""POST /v1/oauth/logout: revoke the refresh token and return Hydra's logout URL."""

from dataclasses import dataclass

from app.modules.identity.application.consent_support import parse_uuid
from app.modules.identity.application.token_grant import require_web_client
from app.modules.identity.domain.errors import HydraUnavailableError
from app.modules.identity.ports.hydra_gateway import HydraGateway
from app.modules.identity.ports.revocation_list import RevocationList
from app.modules.identity.ports.unit_of_work import UowFactory
from app.shared.clock import Clock

import structlog

log = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class LogOutClient:
    """Ends the session behind a refresh token; Hydra's SSO session ends via the URL."""

    uow_factory: UowFactory
    hydra: HydraGateway
    revocations: RevocationList
    clock: Clock
    logout_url: str

    async def execute(self, client_id: str, refresh_token: str | None) -> str:
        """Return the Hydra end-session URL the browser should open."""
        require_web_client(client_id)
        if refresh_token:
            await self._revoke_session(refresh_token)
            await self.hydra.revoke_token(client_id, refresh_token)
        return self.logout_url

    async def _revoke_session(self, refresh_token: str) -> None:
        try:
            info = await self.hydra.introspect(refresh_token)
        except HydraUnavailableError:
            log.warning("logout_introspect_failed")
            return
        if not info.get("active"):
            return
        session_id = parse_uuid((info.get("ext") or {}).get("sid"))
        if session_id is None:
            return
        async with self.uow_factory() as uow:
            await uow.sessions.revoke(session_id, self.clock.now())
            await uow.commit()
        await self.revocations.revoke(session_id)
