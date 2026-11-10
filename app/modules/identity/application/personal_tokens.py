"""Personal API tokens: create (OTP step-up), list and revoke."""

from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from app.modules.identity.application.audit_drafts import make_audit
from app.modules.identity.application.load_user import require_user
from app.modules.identity.application.otp_service import OtpService
from app.modules.identity.application.request_context import RequestContext
from app.modules.identity.domain.audit_event import (
    PERSONAL_TOKEN_CREATED,
    PERSONAL_TOKEN_REVOKED,
)
from app.modules.identity.domain.errors import (
    PersonalTokenInvalidError,
    SecondFactorRequiredError,
)
from app.modules.identity.domain.personal_token import (
    ALLOWED_EXPIRY_DAYS,
    MAX_NAME_LENGTH,
    PersonalToken,
    PersonalTokenScope,
    new_token,
)
from app.modules.identity.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from app.shared.base_error import NotFoundError
from app.shared.clock import Clock
from app.shared.ids import new_id

_SCOPES = frozenset(scope.value for scope in PersonalTokenScope)


@dataclass(frozen=True, slots=True)
class NewPersonalToken:
    """The stored token and its secret, shown once."""

    token: PersonalToken
    secret: str


@dataclass(frozen=True, slots=True)
class CreatePersonalToken:
    """Issues a hashed personal token after an OTP step-up."""

    uow_factory: UowFactory
    otp: OtpService
    clock: Clock

    async def execute(
        self,
        actor: Actor,
        *,
        name: str,
        scopes: list[str],
        expires_in_days: int,
        otp_code: str | None,
        ctx: RequestContext,
    ) -> NewPersonalToken:
        """Create the token and return the secret (never stored in clear)."""
        name = name.strip()
        unique_scopes = list(dict.fromkeys(scopes))
        self._validate(name, unique_scopes, expires_in_days)
        async with self.uow_factory() as uow:
            user = await require_user(uow, actor.user_id)
            if not otp_code:
                raise SecondFactorRequiredError(params={"action": "personal-token"})
            await self.otp.check("step-up", str(user.id), otp_code)
            secret, token_hash, prefix = new_token()
            token = PersonalToken(
                id=new_id(),
                user_id=user.id,
                name=name,
                prefix=prefix,
                token_hash=token_hash,
                scopes=unique_scopes,
                expires_at=self.clock.now() + timedelta(days=expires_in_days),
                created_at=self.clock.now(),
            )
            await uow.personal_tokens.add(token)
            uow.audit(
                make_audit(
                    PERSONAL_TOKEN_CREATED,
                    user_id=user.id,
                    ctx=ctx,
                    token_id=str(token.id),
                    scopes=unique_scopes,
                    expires_in_days=expires_in_days,
                )
            )
            await uow.commit()
        return NewPersonalToken(token=token, secret=secret)

    @staticmethod
    def _validate(name: str, scopes: list[str], expires_in_days: int) -> None:
        reasons: list[str] = []
        if not name or len(name) > MAX_NAME_LENGTH:
            reasons.append("name")
        if not scopes or not set(scopes) <= _SCOPES:
            reasons.append("scopes")
        if expires_in_days not in ALLOWED_EXPIRY_DAYS:
            reasons.append("expires_in_days")
        if reasons:
            raise PersonalTokenInvalidError(params={"fields": reasons})


@dataclass(frozen=True, slots=True)
class ListPersonalTokens:
    """Lists the caller's tokens, newest first, revoked ones included."""

    uow_factory: UowFactory

    async def execute(self, actor: Actor) -> list[PersonalToken]:
        """Return every token of the caller."""
        async with self.uow_factory() as uow:
            return await uow.personal_tokens.list_for_user(actor.user_id)


@dataclass(frozen=True, slots=True)
class RevokePersonalToken:
    """Revokes one of the caller's tokens; it stops working at once."""

    uow_factory: UowFactory
    clock: Clock

    async def execute(self, actor: Actor, token_id: UUID, ctx: RequestContext) -> None:
        """Revoke the token (a second call changes nothing)."""
        async with self.uow_factory() as uow:
            token = await uow.personal_tokens.get(token_id)
            if token is None or token.user_id != actor.user_id:
                raise NotFoundError(params={"token_id": str(token_id)})
            if token.revoked_at is not None:
                return
            token.revoked_at = self.clock.now()
            await uow.personal_tokens.save(token)
            uow.audit(
                make_audit(
                    PERSONAL_TOKEN_REVOKED,
                    user_id=actor.user_id,
                    ctx=ctx,
                    token_id=str(token.id),
                )
            )
            await uow.commit()
