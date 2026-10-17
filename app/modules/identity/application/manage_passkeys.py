"""/v1/id/me/passkeys and /v1/id/me/password-login: passkeys of the signed-in user."""

import base64
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.modules.identity.application.audit_drafts import make_audit
from app.modules.identity.application.factor_support import load_factors
from app.modules.identity.application.load_user import require_user
from app.modules.identity.application.request_context import RequestContext
from app.modules.identity.domain.audit_event import (
    PASSKEY_ADDED,
    PASSKEY_REMOVED,
    PASSWORD_LOGIN_DISABLED,
)
from app.modules.identity.domain.errors import (
    LastPasskeyError,
    PasskeyInvalidError,
    PasskeyNotFoundError,
    PasskeyRequiredError,
)
from app.modules.identity.domain.factors import Passkey
from app.modules.identity.ports.ticket_store import TicketStore
from app.modules.identity.ports.unit_of_work import IdentityUnitOfWorkPort, UowFactory
from app.modules.identity.ports.webauthn import WebAuthn
from app.shared.actor import Actor
from app.shared.clock import Clock
from app.shared.ids import new_id

CEREMONY_TTL_SECONDS = 300
MAX_PASSKEYS = 20


def encode_challenge(challenge: bytes) -> str:
    """Base64 for the ticket store."""
    return base64.b64encode(challenge).decode()


def decode_challenge(value: object) -> bytes:
    """Reverse ``encode_challenge``."""
    return base64.b64decode(str(value))


@dataclass(frozen=True, slots=True)
class SecurityOverview:
    """GET /v1/id/me/security."""

    totp_enabled: bool
    recovery_codes_left: int
    password_login_enabled: bool
    passkeys: list[Passkey]


@dataclass(frozen=True, slots=True)
class ManagePasskeys:
    """Register, list, rename and remove passkeys; turn password sign-in off."""

    uow_factory: UowFactory
    webauthn: WebAuthn
    tickets: TicketStore
    clock: Clock

    async def overview(self, actor: Actor) -> SecurityOverview:
        """The sign-in factors of the user."""
        async with self.uow_factory() as uow:
            user = await require_user(uow, actor.user_id)
            factors = await load_factors(uow, user.id)
            passkeys = await uow.factors.list_passkeys(user.id)
        return SecurityOverview(
            totp_enabled=factors.totp_enabled,
            recovery_codes_left=(
                len(factors.recovery_code_hashes) if factors.totp_enabled else 0
            ),
            password_login_enabled=not factors.password_login_disabled,
            passkeys=passkeys,
        )

    async def registration_options(self, actor: Actor) -> dict[str, Any]:
        """Options for navigator.credentials.create; valid for 5 minutes."""
        async with self.uow_factory() as uow:
            user = await require_user(uow, actor.user_id)
            existing = await uow.factors.list_passkeys(user.id)
        ceremony = self.webauthn.registration_options(
            user_id=user.id.bytes,
            user_name=user.login or str(user.id),
            display_name=user.full_name,
            exclude=[p.credential_id for p in existing],
        )
        await self.tickets.put(
            f"passkey-reg:{user.id}",
            {"challenge": encode_challenge(ceremony.challenge)},
            ttl=CEREMONY_TTL_SECONDS,
        )
        return ceremony.options

    async def register(
        self,
        actor: Actor,
        credential: dict[str, Any],
        name: str,
        ctx: RequestContext,
    ) -> Passkey:
        """Verify the browser's answer and store the passkey."""
        key = f"passkey-reg:{actor.user_id}"
        pending = await self.tickets.get(key)
        if pending is None:
            raise PasskeyInvalidError(params={"reason": "expired"})
        await self.tickets.delete(key)
        verified = self.webauthn.verify_registration(
            credential, decode_challenge(pending["challenge"])
        )
        async with self.uow_factory() as uow:
            user = await require_user(uow, actor.user_id)
            if await uow.factors.get_passkey_by_credential(verified.credential_id):
                raise PasskeyInvalidError(params={"reason": "duplicate"})
            if len(await uow.factors.list_passkeys(user.id)) >= MAX_PASSKEYS:
                raise PasskeyInvalidError(params={"reason": "too-many"})
            passkey = Passkey(
                id=new_id(),
                user_id=user.id,
                credential_id=verified.credential_id,
                public_key=verified.public_key,
                sign_count=verified.sign_count,
                name=name.strip() or "Passkey",
                created_at=self.clock.now(),
                transports=verified.transports,
                backed_up=verified.backed_up,
            )
            await uow.factors.add_passkey(passkey)
            uow.audit(
                make_audit(
                    PASSKEY_ADDED, user_id=user.id, ctx=ctx, passkey_id=str(passkey.id)
                )
            )
            await uow.commit()
        return passkey

    async def rename(self, actor: Actor, passkey_id: UUID, name: str) -> Passkey:
        """Change the label."""
        async with self.uow_factory() as uow:
            passkey = await self._own(uow, actor, passkey_id)
            passkey.name = name.strip() or passkey.name
            await uow.factors.save_passkey(passkey)
            await uow.commit()
        return passkey

    async def delete(self, actor: Actor, passkey_id: UUID, ctx: RequestContext) -> None:
        """Remove a passkey; the last one stays while password sign-in is off."""
        async with self.uow_factory() as uow:
            passkey = await self._own(uow, actor, passkey_id)
            factors = await load_factors(uow, actor.user_id)
            count = len(await uow.factors.list_passkeys(actor.user_id))
            if factors.password_login_disabled and count <= 1:
                raise LastPasskeyError()
            await uow.factors.delete_passkey(passkey.id)
            uow.audit(
                make_audit(
                    PASSKEY_REMOVED,
                    user_id=actor.user_id,
                    ctx=ctx,
                    passkey_id=str(passkey.id),
                )
            )
            await uow.commit()

    async def disable_password_login(self, actor: Actor, ctx: RequestContext) -> None:
        """Only with at least one passkey; a password reset turns it back on."""
        async with self.uow_factory() as uow:
            user = await require_user(uow, actor.user_id)
            if not await uow.factors.list_passkeys(user.id):
                raise PasskeyRequiredError()
            factors = await load_factors(uow, user.id)
            if not factors.password_login_disabled:
                factors.password_login_disabled = True
                await uow.factors.save(factors)
                uow.audit(make_audit(PASSWORD_LOGIN_DISABLED, user_id=user.id, ctx=ctx))
            await uow.commit()

    async def _own(
        self, uow: IdentityUnitOfWorkPort, actor: Actor, passkey_id: UUID
    ) -> Passkey:
        passkey = await uow.factors.get_passkey(passkey_id)
        if passkey is None or passkey.user_id != actor.user_id:
            raise PasskeyNotFoundError()
        return passkey
