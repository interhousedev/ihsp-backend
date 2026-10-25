"""POST /v1/oauth/refresh: rotate the refresh token from the cookie."""

from dataclasses import dataclass
from datetime import timedelta

from app.modules.identity.application.consent_support import parse_uuid
from app.modules.identity.application.token_grant import TokenGrant, require_web_client
from app.modules.identity.domain.jwt_claims import unverified_claims
from app.modules.identity.ports.hydra_gateway import HydraGateway
from app.modules.identity.ports.unit_of_work import UowFactory
from app.shared.clock import Clock

TOUCH_INTERVAL = timedelta(minutes=1)


@dataclass(frozen=True, slots=True)
class RefreshTokens:
    """Rotates at Hydra and records that the session is still in use."""

    uow_factory: UowFactory
    hydra: HydraGateway
    clock: Clock

    async def execute(self, client_id: str, refresh_token: str) -> TokenGrant:
        """Return new tokens; Hydra and the token hook refuse revoked sessions."""
        require_web_client(client_id)
        tokens = await self.hydra.refresh(client_id, refresh_token)
        await self._touch(tokens.access_token)
        return TokenGrant(
            access_token=tokens.access_token,
            expires_in=tokens.expires_in,
            refresh_token=tokens.refresh_token,
        )

    async def _touch(self, access_token: str) -> None:
        # The token came straight from Hydra, so reading it unverified is safe here.
        ext = unverified_claims(access_token).get("ext") or {}
        session_id = parse_uuid(ext.get("sid"))
        if session_id is None:
            return
        async with self.uow_factory() as uow:
            await uow.sessions.touch(
                session_id, self.clock.now(), min_interval=TOUCH_INTERVAL
            )
            await uow.commit()
