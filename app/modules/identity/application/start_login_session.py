"""Create the Session row and accept the Hydra login (shared by all login paths)."""

from collections.abc import Sequence
from dataclasses import dataclass

from app.modules.identity.application.audit_drafts import make_audit
from app.modules.identity.application.request_context import RequestContext
from app.modules.identity.domain.audit_event import LOGIN_SUCCESS
from app.modules.identity.domain.session import SESSION_LIFETIME, LoginSession
from app.modules.identity.domain.user import User
from app.modules.identity.ports.hydra_gateway import HydraGateway, LoginRequest
from app.modules.identity.ports.unit_of_work import IdentityUnitOfWorkPort
from app.shared.clock import Clock
from app.shared.ids import new_id

REMEMBER_FOR_SECONDS = 30 * 24 * 3600


@dataclass(frozen=True, slots=True)
class LoginSessionStarter:
    """Writes the session in the open unit of work, commits, then tells Hydra."""

    hydra: HydraGateway
    clock: Clock

    async def start(
        self,
        uow: IdentityUnitOfWorkPort,
        request: LoginRequest,
        user: User,
        *,
        amr: Sequence[str],
        mfa: bool,
        ctx: RequestContext,
        remember: bool,
    ) -> str:
        """Return the URL to send the browser to. The unit of work is committed."""
        now = self.clock.now()
        session = await self._session_for(uow, request, user, list(amr), mfa, ctx)
        user.last_login_at = now
        await uow.users.save(user)
        uow.audit(
            make_audit(
                LOGIN_SUCCESS,
                user_id=user.id,
                ctx=ctx,
                amr=list(amr),
                client_id=request.client.client_id,
            )
        )
        await uow.commit()
        return await self.hydra.accept_login(
            request.challenge,
            subject=str(user.id),
            remember=remember,
            remember_for=REMEMBER_FOR_SECONDS if remember else 0,
            amr=list(amr),
            context={
                "session_id": str(session.id),
                "amr": list(amr),
                "mfa_at": session.mfa_at.isoformat() if session.mfa_at else None,
            },
        )

    async def _session_for(
        self,
        uow: IdentityUnitOfWorkPort,
        request: LoginRequest,
        user: User,
        amr: list[str],
        mfa: bool,
        ctx: RequestContext,
    ) -> LoginSession:
        now = self.clock.now()
        existing = (
            await uow.sessions.get_by_hydra_sid(request.session_id)
            if request.session_id
            else None
        )
        if existing is not None and existing.user_id == user.id:
            # Same browser logs in again (e.g. the admin 12 hour rule): reuse the row.
            existing.amr = amr
            existing.mfa_at = now if mfa else existing.mfa_at
            existing.ip = ctx.session_ip
            existing.user_agent = ctx.device
            existing.last_seen_at = now
            existing.expires_at = now + SESSION_LIFETIME
            existing.revoked_at = None
            await uow.sessions.save(existing)
            return existing
        session = LoginSession(
            id=new_id(),
            user_id=user.id,
            ip=ctx.session_ip,
            user_agent=ctx.device,
            expires_at=now + SESSION_LIFETIME,
            last_seen_at=now,
            hydra_sid=None if existing else request.session_id,
            amr=amr,
            mfa_at=now if mfa else None,
        )
        await uow.sessions.add(session)
        return session
