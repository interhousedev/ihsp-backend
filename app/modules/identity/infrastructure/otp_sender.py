"""Delivers one-time codes through linked Telegram accounts and the recovery email."""

from collections.abc import Sequence
from datetime import timedelta
from html import escape
from typing import Any

from app.modules.identity.domain.errors import EmailDeliveryError
from app.modules.identity.domain.telegram_link import TelegramLink
from app.modules.identity.ports.email_sender import EmailSender
from app.modules.identity.ports.otp_sender import (
    CHANNEL_EMAIL,
    CHANNEL_TELEGRAM,
    OtpContext,
)
from app.modules.identity.ports.unit_of_work import UowFactory
from app.shared.clock import Clock
from app.shared.contracts.identity import UserRef
from app.shared.contracts.notify import TelegramSender
from app.shared.i18n.core import I18nCore

import structlog
from redis.asyncio import Redis

log = structlog.get_logger(__name__)

CLEANUP_KEY = "tg:otp-msgs"
CLEANUP_AFTER = timedelta(minutes=5)


class ChannelOtpSender:
    """OtpSender: a failing channel is logged and never blocks the others."""

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        email: EmailSender,
        telegram: TelegramSender | None,
        i18n: I18nCore,
        redis: Redis,
        clock: Clock,
        id_app_url: str,
        app_name: str = "IHSP",
    ) -> None:
        """Keep the collaborators; ``telegram`` is None until the sender is wired."""
        self._uow_factory = uow_factory
        self._email = email
        self._telegram = telegram
        self._i18n = i18n
        self._redis = redis
        self._clock = clock
        self._security_url = f"{id_app_url.rstrip('/')}/security/"
        self._app_name = app_name

    async def send_code(
        self,
        user: UserRef,
        code: str,
        *,
        purpose: str,
        channels: Sequence[str],
        context: OtpContext | None = None,
    ) -> None:
        """Send the code to each requested channel."""
        async with self._uow_factory() as uow:
            entity = await uow.users.get(user.id)
            links = await uow.telegram_links.list_for_user(user.id)
        if CHANNEL_TELEGRAM in channels:
            await self._to_telegram(user, code, links, context or OtpContext())
        if CHANNEL_EMAIL in channels and entity and entity.recovery_email:
            await self._to_email(entity.recovery_email, code, user.locale, purpose)

    async def _to_telegram(
        self,
        user: UserRef,
        code: str,
        links: list[TelegramLink],
        context: OtpContext,
    ) -> None:
        telegram = self._telegram
        if telegram is None:
            log.warning("otp_telegram_skipped", reason="no telegram sender")
            return
        ctx = self._i18n.get_context(user.locale)
        text = ctx.get(
            "id-otp-telegram",
            app_name=self._app_name,
            code=escape(code),
            ip=escape(context.ip or "?"),
            device=escape((context.user_agent or "?")[:80]),
        )
        buttons = [[{"text": ctx.get("id-btn-not-me"), "url": self._security_url}]]
        for link in links:
            if not link.can_receive_otp:
                continue
            await self._send_one(telegram, link.telegram_user_id, text, buttons)

    async def _send_one(
        self,
        telegram: TelegramSender,
        chat_id: int,
        text: str,
        buttons: list[list[dict[str, Any]]],
    ) -> None:
        try:
            message_id = await telegram.send_message(chat_id, text, buttons)
        except Exception:  # noqa: BLE001 - one dead chat must not block other channels
            log.warning("otp_telegram_failed", chat_id=chat_id, exc_info=True)
            return
        delete_at = (self._clock.now() + CLEANUP_AFTER).timestamp()
        await self._redis.zadd(CLEANUP_KEY, {f"{chat_id}:{message_id}": delete_at})

    async def _to_email(
        self, address: str, code: str, locale: str, purpose: str
    ) -> None:
        try:
            await self._email.send(
                address, "otp", {"code": code, "purpose": purpose}, locale
            )
        except EmailDeliveryError:
            log.warning("otp_email_failed", purpose=purpose)
