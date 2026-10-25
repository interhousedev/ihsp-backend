"""GET /v1/id/logout: accept Hydra's logout request and close our session."""

from dataclasses import dataclass

from app.modules.identity.application.audit_drafts import make_audit
from app.modules.identity.domain.audit_event import LOGOUT
from app.modules.identity.ports.hydra_gateway import HydraGateway
from app.modules.identity.ports.revocation_list import RevocationList
from app.modules.identity.ports.unit_of_work import UowFactory
from app.shared.clock import Clock


@dataclass(frozen=True, slots=True)
class AcceptLogout:
    """Marks the Session of the Hydra login session as revoked, then accepts."""

    uow_factory: UowFactory
    hydra: HydraGateway
    revocations: RevocationList
    clock: Clock

    async def execute(self, challenge: str) -> str:
        """Return the URL to send the browser to."""
        request = await self.hydra.get_logout_request(challenge)
        if request.sid:
            await self._revoke_session(request.sid)
        return await self.hydra.accept_logout(challenge)

    async def _revoke_session(self, hydra_sid: str) -> None:
        async with self.uow_factory() as uow:
            session = await uow.sessions.get_by_hydra_sid(hydra_sid)
            if session is None:
                return
            revoked = await uow.sessions.revoke(session.id, self.clock.now())
            if revoked is not None:
                uow.audit(make_audit(LOGOUT, user_id=session.user_id))
            await uow.commit()
        await self.revocations.revoke(session.id)
