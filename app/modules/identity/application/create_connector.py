"""POST /v1/id/me/connectors: issue an MCP token connector (MCP-2)."""

from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from app.modules.identity.application.audit_drafts import make_audit
from app.modules.identity.application.load_user import require_user
from app.modules.identity.application.otp_service import OtpService
from app.modules.identity.application.request_context import RequestContext
from app.modules.identity.domain.audit_event import CONNECTOR_CREATED
from app.modules.identity.domain.connector import (
    ADMIN_MAX_EXPIRY_DAYS,
    ALLOWED_EXPIRY_DAYS,
    McpConnector,
    new_token,
)
from app.modules.identity.domain.errors import (
    ConnectorInvalidError,
    RoleMissingError,
    SecondFactorRequiredError,
)
from app.modules.identity.domain.scopes import role_may_use_server, scope_names
from app.modules.identity.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from app.shared.clock import Clock
from app.shared.ids import new_id

MAX_NAME_LENGTH = 80


@dataclass(frozen=True, slots=True)
class NewConnector:
    """The stored connector and the token, shown once."""

    connector: McpConnector
    token: str


@dataclass(frozen=True, slots=True)
class CreateConnector:
    """Validates the request against the server's rules and stores a hashed token."""

    uow_factory: UowFactory
    otp: OtpService
    clock: Clock

    async def execute(
        self,
        actor: Actor,
        *,
        server: str,
        name: str,
        scopes: list[str],
        course_ids: list[UUID] | None,
        expires_in_days: int,
        otp_code: str | None,
        ctx: RequestContext,
    ) -> NewConnector:
        """Create the connector and return the token (never stored in clear)."""
        name = name.strip()
        unique_scopes = list(dict.fromkeys(scopes))
        self._validate(server, name, unique_scopes, course_ids, expires_in_days)
        async with self.uow_factory() as uow:
            user = await require_user(uow, actor.user_id)
            if not role_may_use_server(user.roles, server):
                raise RoleMissingError(params={"server": server})
            if server == "admin":
                if not otp_code:
                    raise SecondFactorRequiredError(params={"server": server})
                await self.otp.check("step-up", str(user.id), otp_code)
            token, token_hash, prefix = new_token()
            connector = McpConnector(
                id=new_id(),
                user_id=user.id,
                name=name,
                server=server,
                scopes=unique_scopes,
                course_ids=course_ids,
                token_hash=token_hash,
                token_prefix=prefix,
                expires_at=self.clock.now() + timedelta(days=expires_in_days),
            )
            await uow.connectors.add(connector)
            uow.audit(
                make_audit(
                    CONNECTOR_CREATED,
                    user_id=user.id,
                    ctx=ctx,
                    connector_id=str(connector.id),
                    server=server,
                    scopes=unique_scopes,
                    via="token",
                )
            )
            await uow.commit()
        return NewConnector(connector=connector, token=token)

    @staticmethod
    def _validate(
        server: str,
        name: str,
        scopes: list[str],
        course_ids: list[UUID] | None,
        expires_in_days: int,
    ) -> None:
        reasons: list[str] = []
        known = scope_names(server)
        if not known:
            reasons.append("server")
        if not name or len(name) > MAX_NAME_LENGTH:
            reasons.append("name")
        if not scopes or not set(scopes) <= known:
            reasons.append("scopes")
        if course_ids is not None and server != "lms":
            reasons.append("course_ids")
        if expires_in_days not in ALLOWED_EXPIRY_DAYS:
            reasons.append("expires_in_days")
        if server == "admin" and expires_in_days > ADMIN_MAX_EXPIRY_DAYS:
            reasons.append("expires_in_days")
        if reasons:
            raise ConnectorInvalidError(params={"fields": sorted(set(reasons))})
