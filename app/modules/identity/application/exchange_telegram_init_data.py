"""POST /v1/oauth/telegram: mini app login with signed initData (no cookie)."""

from dataclasses import dataclass
from datetime import timedelta

from app.modules.identity.application.audit_drafts import make_audit
from app.modules.identity.application.request_context import RequestContext
from app.modules.identity.application.token_grant import TokenGrant
from app.modules.identity.domain.audit_event import LOGIN_SUCCESS
from app.modules.identity.domain.client_policy import may_use_client
from app.modules.identity.domain.errors import RoleMissingError, UnknownClientError
from app.modules.identity.domain.session import SESSION_LIFETIME, LoginSession
from app.modules.identity.ports.assertion_signer import AssertionSigner
from app.modules.identity.ports.hydra_gateway import HydraGateway
from app.modules.identity.ports.init_data_verifier import InitDataVerifier
from app.modules.identity.ports.unit_of_work import UowFactory
from app.shared.base_error import UnauthorizedError
from app.shared.clock import Clock
from app.shared.contracts.auth import AUDIENCE_API
from app.shared.ids import new_id

MINIAPP_CLIENTS = frozenset({"sp", "staff"})
# initData is re-sent on every 401 while the mini app stays open (architecture.md).
INIT_DATA_MAX_AGE = timedelta(hours=24)
TOKEN_SCOPE = "openid offline_access"


@dataclass(frozen=True, slots=True)
class ExchangeTelegramInitData:
    """Telegram vouches for the account, our own signed assertion gets the token."""

    uow_factory: UowFactory
    hydra: HydraGateway
    verifier: InitDataVerifier
    signer: AssertionSigner
    clock: Clock

    async def execute(
        self, client_id: str, init_data: str, ctx: RequestContext
    ) -> TokenGrant:
        """Return an access token for the linked account (never a refresh token)."""
        if client_id not in MINIAPP_CLIENTS:
            raise UnknownClientError(params={"client_id": client_id})
        telegram_user = self.verifier.verify(init_data, max_age=INIT_DATA_MAX_AGE)
        now = self.clock.now()
        async with self.uow_factory() as uow:
            link = await uow.telegram_links.get(telegram_user.id)
            user = await uow.users.get(link.user_id) if link else None
            if link is None or user is None or not user.is_active:
                raise UnauthorizedError(support_details="telegram account not linked")
            if not may_use_client(client_id, user.roles):
                raise RoleMissingError(params={"client_id": client_id})
            session = LoginSession(
                id=new_id(),
                user_id=user.id,
                ip=ctx.session_ip,
                user_agent=ctx.device,
                expires_at=now + SESSION_LIFETIME,
                last_seen_at=now,
                amr=["tg"],
            )
            await uow.sessions.add(session)
            link.last_seen_at = now
            await uow.telegram_links.save(link)
            uow.audit(
                make_audit(
                    LOGIN_SUCCESS,
                    user_id=user.id,
                    ctx=ctx,
                    amr=["tg"],
                    client_id=client_id,
                )
            )
            await uow.commit()
        assertion = self.signer.sign(user.id, session.id, ["tg"])
        tokens = await self.hydra.jwt_bearer(assertion, TOKEN_SCOPE, AUDIENCE_API)
        return TokenGrant(
            access_token=tokens.access_token, expires_in=tokens.expires_in
        )
