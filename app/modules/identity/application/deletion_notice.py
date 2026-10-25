"""Tell a user on Telegram that their account is scheduled for deletion."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from html import escape
from uuid import UUID

from app.modules.identity.ports.unit_of_work import UowFactory
from app.shared.clock import to_local
from app.shared.contracts.notify import TelegramSender
from app.shared.i18n.core import I18nCore

import structlog

log = structlog.get_logger(__name__)

DEFAULT_LOCALE = "ru"


def deletion_date(requested_at: datetime, days: int) -> date:
    """The local (Tashkent) day the account is purged."""
    return to_local(requested_at).date() + timedelta(days=days)


@dataclass(frozen=True, slots=True)
class DeletionTelegramNotice:
    """Message every linked Telegram chat; a dead chat never blocks the others."""

    uow_factory: UowFactory
    telegram: TelegramSender | None
    i18n: I18nCore
    id_app_url: str

    async def __call__(self, user_id: UUID, deletes_on: date) -> None:
        """Send the notice (best effort)."""
        if self.telegram is None:
            return
        async with self.uow_factory() as uow:
            user = await uow.users.get(user_id)
            links = await uow.telegram_links.list_for_user(user_id)
        if user is None or not links:
            return
        ctx = self.i18n.get_context(user.locale or DEFAULT_LOCALE)
        url = f"{self.id_app_url.rstrip('/')}/login/"
        text = ctx.get(
            "id-deletion-scheduled-telegram",
            deletes_on=escape(deletes_on.isoformat()),
            url=escape(url),
        )
        buttons = [[{"text": ctx.get("id-btn-restore-account"), "url": url}]]
        for link in links:
            try:
                await self.telegram.send_message(link.telegram_user_id, text, buttons)
            except Exception:  # noqa: BLE001 - one dead chat must not block others
                log.warning("deletion_notice_telegram_failed", exc_info=True)
