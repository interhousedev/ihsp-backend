"""POST /v1/id/consent: the user approves or denies an MCP client."""

from dataclasses import dataclass
from datetime import timedelta

from app.modules.identity.application.audit_drafts import make_audit
from app.modules.identity.application.auto_accept_consent import AutoAcceptConsent
from app.modules.identity.application.consent_support import (
    access_claims,
    grantable,
    is_dynamic,
    is_verified,
    mcp_server,
    parse_datetime,
    parse_uuid,
    requested_scopes,
)
from app.modules.identity.application.otp_service import OtpService
from app.modules.identity.application.request_context import RequestContext
from app.modules.identity.domain.audit_event import CONNECTOR_CREATED
from app.modules.identity.domain.client_policy import is_first_party
from app.modules.identity.domain.connector import (
    ADMIN_MAX_EXPIRY_DAYS,
    OAUTH_EXPIRY_DAYS,
    McpConnector,
)
from app.modules.identity.domain.errors import (
    AdminServerForbiddenError,
    RoleMissingError,
    SecondFactorRequiredError,
    UserNotFoundError,
)
from app.modules.identity.domain.scopes import AUDIENCE_BY_SERVER, role_may_use_server
from app.modules.identity.domain.session import ADMIN_MFA_WINDOW
from app.modules.identity.domain.user import User
from app.modules.identity.ports.hydra_gateway import ConsentRequest, HydraGateway
from app.modules.identity.ports.unit_of_work import UowFactory
from app.shared.clock import Clock
from app.shared.ids import new_id

OPENID_SCOPES = ("openid", "offline_access", "offline")


@dataclass(frozen=True, slots=True)
class AcceptConsent:
    """Creates the OAuth connector and hands the claims to Hydra."""

    uow_factory: UowFactory
    hydra: HydraGateway
    otp: OtpService
    auto_accept: AutoAcceptConsent
    clock: Clock

    async def execute(
        self,
        challenge: str,
        *,
        accept: bool,
        grant_scopes: list[str],
        otp_code: str | None,
        ctx: RequestContext,
    ) -> str:
        """Return the URL to send the browser to."""
        request = await self.hydra.get_consent_request(challenge)
        if is_first_party(request.client.client_id):
            return await self.auto_accept.execute(request)
        if not accept:
            return await self.hydra.reject_consent(
                challenge, "access_denied", "the user denied the request"
            )
        return await self._accept_mcp(request, grant_scopes, otp_code, ctx)

    async def _accept_mcp(
        self,
        request: ConsentRequest,
        grant_scopes: list[str],
        otp_code: str | None,
        ctx: RequestContext,
    ) -> str:
        server = mcp_server(request)
        scopes = grantable(server, requested_scopes(request, server), grant_scopes)
        user_id = parse_uuid(request.subject)
        async with self.uow_factory() as uow:
            found = await uow.users.get(user_id) if user_id else None
            user = self._require_user(found, server)
            client = request.client
            if server == "admin":
                if is_dynamic(client) and not is_verified(client):
                    raise AdminServerForbiddenError(
                        params={"client_id": client.client_id}
                    )
                await self._check_admin_step_up(user, request, otp_code)
            connector = self._connector(user, request, server, scopes)
            await uow.connectors.add(connector)
            uow.audit(
                make_audit(
                    CONNECTOR_CREATED,
                    user_id=user.id,
                    ctx=ctx,
                    connector_id=str(connector.id),
                    server=server,
                    via="oauth",
                    client_id=client.client_id,
                )
            )
            await uow.commit()
        return await self._accept(request, user, connector, scopes)

    @staticmethod
    def _require_user(user: User | None, server: str) -> User:
        if user is None or not user.is_active:
            raise UserNotFoundError()
        if not role_may_use_server(user.roles, server):
            raise RoleMissingError(params={"server": server})
        return user

    async def _check_admin_step_up(
        self, user: User, request: ConsentRequest, otp_code: str | None
    ) -> None:
        """Administration needs a fresh password + OTP login and a step-up code."""
        mfa_at = parse_datetime(request.context.get("mfa_at"))
        now = self.clock.now()
        if mfa_at is None or now - mfa_at > ADMIN_MFA_WINDOW or not otp_code:
            raise SecondFactorRequiredError(params={"server": "admin"})
        await self.otp.check("step-up", str(user.id), otp_code)

    def _connector(
        self, user: User, request: ConsentRequest, server: str, scopes: list[str]
    ) -> McpConnector:
        now = self.clock.now()
        days = ADMIN_MAX_EXPIRY_DAYS if server == "admin" else OAUTH_EXPIRY_DAYS
        return McpConnector(
            id=new_id(),
            user_id=user.id,
            name=request.client.client_name,
            server=server,
            scopes=scopes,
            hydra_client_id=request.client.client_id,
            expires_at=now + timedelta(days=days),
        )

    async def _accept(
        self,
        request: ConsentRequest,
        user: User,
        connector: McpConnector,
        scopes: list[str],
    ) -> str:
        amr = [str(item) for item in request.context.get("amr") or []]
        mfa_at = request.context.get("mfa_at")
        claims = access_claims(
            user,
            sid=str(connector.id),
            amr=amr,
            mfa_at=mfa_at if isinstance(mfa_at, str) else None,
            extra={"connector_id": str(connector.id), "server": connector.server},
        )
        openid = [s for s in request.requested_scope if s in OPENID_SCOPES]
        return await self.hydra.accept_consent(
            request.challenge,
            grant_scope=[*openid, *scopes],
            grant_audience=[AUDIENCE_BY_SERVER[connector.server]],
            remember=False,
            access_token_claims=claims,
            id_token_claims={},
        )
