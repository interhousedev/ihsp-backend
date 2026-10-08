"""Send due notifications to Telegram (task notify.dispatch_due, BOT-11–15, BOT-22)."""

from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta

from app.modules.notify.application.renderers.registry import RendererRegistry
from app.modules.notify.domain.delivery_outcome import schedule_retry, settle, skip
from app.modules.notify.domain.notification import Notification
from app.modules.notify.domain.notification_status import (
    DeliveryState,
    NotificationStatus,
)
from app.modules.notify.domain.retry_policy import LEASE
from app.modules.notify.domain.telegram_errors import (
    TelegramBlocked,
    TelegramRetryAfter,
    TelegramSendFailed,
)
from app.modules.notify.ports.send_limiter import SendLimiter
from app.modules.notify.ports.unit_of_work import NotifyUnitOfWork
from app.shared.clock import Clock
from app.shared.contracts.identity import (
    IdentityDirectory,
    TelegramAccountRef,
    UserRef,
    UserStatus,
)
from app.shared.contracts.notify import RenderContext, RenderedMessage, TelegramSender
from app.shared.notifications import NotificationType

import structlog

log = structlog.get_logger(__name__)

BATCH_SIZE = 100
MAX_BATCHES = 50

_COUNTED = {
    NotificationStatus.SENT: "sent",
    NotificationStatus.PARTIAL: "partial",
    NotificationStatus.FAILED: "failed",
    NotificationStatus.SKIPPED: "skipped",
}


@dataclass(slots=True)
class DispatchReport:
    """What one run of the dispatcher did."""

    claimed: int = 0
    sent: int = 0
    partial: int = 0
    failed: int = 0
    skipped: int = 0
    rate_limited: bool = False

    def count(self, status: NotificationStatus) -> None:
        """Count one finished notification by its final status."""
        name = _COUNTED.get(status)
        if name is not None:
            setattr(self, name, getattr(self, name) + 1)


def _reschedule(notification: Notification, until: datetime) -> None:
    """Put a row back in the queue; a row with some deliveries is `partial`."""
    notification.status = (
        NotificationStatus.PARTIAL
        if notification.deliveries
        else NotificationStatus.PENDING
    )
    notification.next_attempt_at = until


def _recipients(
    notification: Notification, accounts: Sequence[TelegramAccountRef]
) -> list[TelegramAccountRef]:
    """Accounts to send to: not blocked and not yet delivered."""
    for account in accounts:
        if account.blocked:
            notification.record(account.telegram_user_id, DeliveryState.BLOCKED)
    return [
        a
        for a in accounts
        if not a.blocked and not notification.delivered_to(a.telegram_user_id)
    ]


class DispatchDue:
    """Claims due notifications in batches and delivers them to Telegram."""

    def __init__(
        self,
        *,
        uow_factory: Callable[[], NotifyUnitOfWork],
        identity: IdentityDirectory,
        renderers: RendererRegistry,
        sender: TelegramSender,
        limiter: SendLimiter,
        clock: Clock,
    ) -> None:
        """Store the ports; a unit of work is created for every transaction."""
        self.uow_factory = uow_factory
        self.identity = identity
        self.renderers = renderers
        self.sender = sender
        self.limiter = limiter
        self.clock = clock

    async def execute(self) -> DispatchReport:
        """Deliver every due notification, stopping early on Telegram flood control."""
        report = DispatchReport()
        for _ in range(MAX_BATCHES):
            batch = await self._claim()
            if not batch:
                break
            report.claimed += len(batch)
            for index, notification in enumerate(batch):
                retry_after = await self._process(notification)
                if retry_after is not None:
                    report.rate_limited = True
                    await self._release(batch[index + 1 :], retry_after)
                    log.warning("telegram_flood_control", retry_after=retry_after)
                    return report
                report.count(notification.status)
        log.info("notifications_dispatched", **asdict(report))
        return report

    # - - - Claiming and saving - - -

    async def _claim(self) -> list[Notification]:
        now = self.clock.now()
        async with self.uow_factory() as uow:
            rows = await uow.notifications.claim_due(
                now=now, limit=BATCH_SIZE, lease_until=now + LEASE
            )
            await uow.commit()
        return rows

    async def _save(self, notification: Notification) -> None:
        async with self.uow_factory() as uow:
            await uow.notifications.save_delivery(notification)
            await uow.commit()

    async def _release(
        self, notifications: Sequence[Notification], seconds: float
    ) -> None:
        """Give claimed rows back to the queue after a flood-control pause."""
        if not notifications:
            return
        until = self.clock.now() + timedelta(seconds=seconds)
        async with self.uow_factory() as uow:
            for notification in notifications:
                _reschedule(notification, until)
                await uow.notifications.save_delivery(notification)
            await uow.commit()

    # - - - One notification - - -

    async def _process(self, notification: Notification) -> float | None:
        """Finish one notification; return the wait if Telegram asked for one."""
        user = await self.identity.get_user(notification.user_id)
        if user is None or user.status != UserStatus.ACTIVE:
            await self._skip(notification, "user-inactive")
            return None
        accounts = await self.identity.telegram_accounts(notification.user_id)
        if not accounts:
            await self._skip(notification, "no-telegram")
            return None
        recipients = _recipients(notification, accounts)
        if not recipients:
            await self._settle(notification, accounts)
            return None
        if not await self._wanted(notification):
            await self._skip(notification, "preferences")
            return None
        return await self._render_and_send(notification, user, accounts, recipients)

    async def _wanted(self, notification: Notification) -> bool:
        """Check the mail forwarding switch; producers check other preferences."""
        if notification.type != NotificationType.MAIL:
            return True
        prefs = await self.identity.get_preferences(notification.user_id)
        return prefs.mail_forward_to_telegram

    async def _render_and_send(
        self,
        notification: Notification,
        user: UserRef,
        accounts: Sequence[TelegramAccountRef],
        recipients: Sequence[TelegramAccountRef],
    ) -> float | None:
        renderer = self.renderers.get(notification.type)
        if renderer is None:
            await self._skip(notification, f"no-renderer:{notification.type}")
            return None
        ctx = RenderContext(
            user=user,
            locale=user.locale,
            telegram_user_id=recipients[0].telegram_user_id,
        )
        try:
            message = await renderer(notification.payload, ctx)
        except Exception as exc:  # one bad payload must not stop the whole batch
            log.exception("notification_render_failed", id=str(notification.id))
            await self._retry_later(notification, f"render-failed:{type(exc).__name__}")
            return None
        if message is None:
            await self._skip(notification, "nothing-to-send")
            return None
        return await self._deliver(notification, message, accounts, recipients)

    # - - - Delivery - - -

    async def _deliver(
        self,
        notification: Notification,
        message: RenderedMessage,
        accounts: Sequence[TelegramAccountRef],
        recipients: Sequence[TelegramAccountRef],
    ) -> float | None:
        errors: list[str] = []
        for account in recipients:
            chat_id = account.telegram_user_id
            try:
                note = await self._send(chat_id, message)
            except TelegramBlocked:
                notification.record(chat_id, DeliveryState.BLOCKED)
                await self.identity.set_telegram_blocked(chat_id, True)
            except TelegramRetryAfter as exc:
                await self._pause(notification, exc.seconds)
                return exc.seconds
            except TelegramSendFailed as exc:
                notification.record(chat_id, DeliveryState.FAILED)
                errors.append(f"{chat_id}:{exc}")
            else:
                notification.record(chat_id, DeliveryState.SENT)
                if note is not None:
                    errors.append(note)
        notification.attempts += 1
        notification.error = "; ".join(errors) or None
        await self._settle(notification, accounts)
        return None

    async def _send(self, chat_id: int, message: RenderedMessage) -> str | None:
        """Send the text and the documents; a failed document is only noted."""
        await self.limiter.acquire()
        await self.sender.send_message(chat_id, message.text_html, message.buttons)
        for filename, data in message.documents:
            await self.limiter.acquire()
            try:
                await self.sender.send_document(chat_id, filename, data)
            except TelegramSendFailed as exc:
                log.warning("notification_document_failed", chat_id=chat_id)
                return f"{chat_id}:document {filename}:{exc}"
        return None

    # - - - Outcomes - - -

    async def _settle(
        self, notification: Notification, accounts: Sequence[TelegramAccountRef]
    ) -> None:
        ids = [account.telegram_user_id for account in accounts]
        settle(notification, ids, self.clock.now())
        await self._save(notification)

    async def _skip(self, notification: Notification, reason: str) -> None:
        skip(notification, reason)
        await self._save(notification)

    async def _retry_later(self, notification: Notification, reason: str) -> None:
        notification.attempts += 1
        notification.error = reason
        schedule_retry(notification, self.clock.now())
        await self._save(notification)

    async def _pause(self, notification: Notification, seconds: float) -> None:
        """Flood control: put the row back without counting an attempt."""
        _reschedule(notification, self.clock.now() + timedelta(seconds=seconds))
        await self._save(notification)
