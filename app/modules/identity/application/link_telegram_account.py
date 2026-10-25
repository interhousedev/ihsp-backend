"""Link a verified Telegram account to a user (ID-18 to ID-21)."""

from dataclasses import dataclass

from app.modules.identity.application.audit_drafts import make_audit
from app.modules.identity.application.notice_email import send_notice
from app.modules.identity.application.request_context import RequestContext
from app.modules.identity.domain.audit_event import TELEGRAM_LINKED
from app.modules.identity.domain.errors import TelegramLinkedElsewhereError
from app.modules.identity.domain.telegram_link import TelegramLink
from app.modules.identity.domain.user import User
from app.modules.identity.ports.email_sender import EmailSender
from app.modules.identity.ports.init_data_verifier import InitDataUser
from app.modules.identity.ports.unit_of_work import IdentityUnitOfWorkPort
from app.shared.clock import Clock
from app.shared.notifications import NotificationDraft, NotificationType


@dataclass(frozen=True, slots=True)
class LinkTelegramAccount:
    """Creates the link, audits it and announces it to the other channels."""

    email: EmailSender
    clock: Clock

    async def execute(
        self,
        uow: IdentityUnitOfWorkPort,
        user: User,
        telegram_user: InitDataUser,
        ctx: RequestContext,
    ) -> bool:
        """Return True for a new link, False if it already belonged to this user."""
        existing = await uow.telegram_links.get(telegram_user.id)
        if existing is not None:
            if existing.user_id != user.id:
                raise TelegramLinkedElsewhereError(
                    params={"telegram_user_id": telegram_user.id}
                )
            return False
        now = self.clock.now()
        await uow.telegram_links.add(
            TelegramLink(
                telegram_user_id=telegram_user.id,
                user_id=user.id,
                first_name=telegram_user.first_name,
                username=telegram_user.username,
                last_seen_at=now,
                linked_at=now,
            )
        )
        uow.audit(
            make_audit(
                TELEGRAM_LINKED,
                user_id=user.id,
                ctx=ctx,
                telegram_user_id=telegram_user.id,
                username=telegram_user.username,
            )
        )
        uow.notify(
            NotificationDraft(
                user_id=user.id,
                type=NotificationType.TELEGRAM_LINKED,
                payload={
                    "telegram_username": telegram_user.username,
                    "telegram_user_id": telegram_user.id,
                },
                dedupe_key=f"tg-linked:{telegram_user.id}:{int(now.timestamp())}",
            )
        )
        locale, address = user.locale, user.recovery_email
        who = (
            f"@{telegram_user.username}"
            if telegram_user.username
            else str(telegram_user.id)
        )

        async def announce() -> None:
            await send_notice(
                self.email,
                address,
                locale,
                "id-mail-notice-telegram-linked",
                {"telegram": who},
            )

        uow.after_commit(announce)
        return True
