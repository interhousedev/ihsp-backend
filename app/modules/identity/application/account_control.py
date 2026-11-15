"""What privacy may do to an account: start its deletion, notify, describe."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any
from uuid import UUID

from app.modules.identity.application.account_revoker_impl import AccountRevokerImpl
from app.modules.identity.application.audit_drafts import make_audit
from app.modules.identity.application.deletion_notice import (
    DeletionTelegramNotice,
    deletion_date,
)
from app.modules.identity.application.request_context import RequestContext
from app.modules.identity.domain.errors import UserNotFoundError
from app.modules.identity.ports.email_sender import EmailSender
from app.modules.identity.ports.unit_of_work import UowFactory
from app.shared.clock import Clock
from app.shared.contracts.privacy import AccountInfo

import structlog

log = structlog.get_logger(__name__)

DELETION_REQUESTED = "account.deletion_requested"


@dataclass(frozen=True, slots=True)
class AccountControlImpl:
    """Implements ``AccountControl`` for the privacy module."""

    uow_factory: UowFactory
    revoker: AccountRevokerImpl
    telegram_notice: DeletionTelegramNotice
    email: EmailSender
    clock: Clock
    retention_days: int

    async def start_deletion(
        self, user_id: UUID, *, approved_by: UUID, ip: str | None
    ) -> date:
        """Mark the account pending deletion, sign it out, tell the owner."""
        now = self.clock.now()
        closes_on = deletion_date(now, self.retention_days)
        async with self.uow_factory() as uow:
            user = await uow.users.get(user_id)
            if user is None:
                raise UserNotFoundError(params={"user_id": str(user_id)})
            user.request_deletion(now)
            await uow.users.save(user)
            uow.audit(
                make_audit(
                    DELETION_REQUESTED,
                    user_id=user_id,
                    ctx=RequestContext(ip=ip),
                    actor_id=approved_by,
                    deletes_on=closes_on.isoformat(),
                )
            )
            await uow.commit()
        # Telegram links stay: they carry the notice and survive a restore.
        await self.revoker.revoke_everything(user_id, keep_telegram=True)
        try:
            await self.telegram_notice(user_id, closes_on)
        except Exception:
            log.exception("deletion telegram notice failed", user=str(user_id))
        await self.send_notice(
            user_id, "id-mail-deletion-scheduled", {"closes_on": closes_on.isoformat()}
        )
        return closes_on

    async def send_notice(
        self, user_id: UUID, text_key: str, params: dict[str, Any]
    ) -> None:
        """Email the recovery address in the user's locale; never raises."""
        try:
            async with self.uow_factory() as uow:
                user = await uow.users.get(user_id)
            if user is None or not user.recovery_email:
                return
            await self.email.send(
                user.recovery_email,
                "notice",
                {"text_key": text_key, "text_params": params},
                user.locale,
            )
        except Exception:
            log.exception("privacy notice failed", user=str(user_id))

    async def describe(self, user_ids: Sequence[UUID]) -> dict[UUID, AccountInfo]:
        """Name, login, roles and status of the accounts."""
        async with self.uow_factory() as uow:
            users = await uow.users.get_many(list(user_ids))
        return {
            uid: AccountInfo(
                user_id=uid,
                name=user.full_name,
                login=user.login,
                roles=frozenset(user.roles),
                status=user.status,
            )
            for uid, user in users.items()
        }
