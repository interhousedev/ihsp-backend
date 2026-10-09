"""Send due notifications over Telegram and Web Push (task notify.dispatch_due)."""

from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta

from app.modules.notify.application.push_delivery import PushDelivery, PushRun
from app.modules.notify.application.renderers.registry import RendererRegistry
from app.modules.notify.domain.delivery_outcome import settle, skip
from app.modules.notify.domain.notification import Notification
from app.modules.notify.domain.notification_status import (
    DeliveryKey,
    DeliveryState,
    NotificationStatus,
)
from app.modules.notify.domain.push_subscription import (
    PushSubscription,
    push_delivery_key,
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
    UserPreferences,
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


@dataclass(slots=True)
class _TelegramRun:
    """What the Telegram channel did for one notification."""

    counts: bool = True
    """False when there was nothing to render: Telegram then stays out of the status."""
    skip_reason: str | None = None
    errors: list[str] = field(default_factory=list)
    retry_after: float | None = None


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


def _undelivered(
    notification: Notification, devices: Sequence[PushSubscription]
) -> list[PushSubscription]:
    """Devices that have not got the notification yet."""
    return [
        d for d in devices if not notification.delivered_to(push_delivery_key(d.id))
    ]


def _all_keys(
    accounts: Sequence[TelegramAccountRef], devices: Sequence[PushSubscription]
) -> list[DeliveryKey]:
    """Delivery keys of every Telegram account and every device."""
    return [
        *(a.telegram_user_id for a in accounts),
        *(push_delivery_key(d.id) for d in devices),
    ]


class DispatchDue:
    """Claims due notifications in batches and delivers them to Telegram and push."""

    def __init__(
        self,
        *,
        uow_factory: Callable[[], NotifyUnitOfWork],
        identity: IdentityDirectory,
        renderers: RendererRegistry,
        sender: TelegramSender,
        limiter: SendLimiter,
        clock: Clock,
        push: PushDelivery | None = None,
    ) -> None:
        """Store the ports; `push` is None while Web Push is switched off."""
        self.uow_factory = uow_factory
        self.identity = identity
        self.renderers = renderers
        self.sender = sender
        self.limiter = limiter
        self.clock = clock
        self.push = push

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
        prefs = await self._preferences(notification)
        if not self._wanted(notification, prefs):
            await self._skip(notification, "preferences")
            return None
        accounts = await self.identity.telegram_accounts(notification.user_id)
        devices = await self._devices(notification, prefs)
        if not accounts and not devices:
            await self._skip(notification, self._no_channel_reason(prefs))
            return None
        recipients = _recipients(notification, accounts)
        if not recipients and not _undelivered(notification, devices):
            await self._settle(notification, _all_keys(accounts, devices))
            return None
        return await self._send(notification, user, accounts, recipients, devices)

    async def _preferences(self, notification: Notification) -> UserPreferences | None:
        """Load the settings only when a rule needs them."""
        if self.push is None and notification.type != NotificationType.MAIL:
            return None
        return await self.identity.get_preferences(notification.user_id)

    @staticmethod
    def _wanted(notification: Notification, prefs: UserPreferences | None) -> bool:
        """Check the mail switch for both channels; producers check the other types."""
        if notification.type != NotificationType.MAIL or prefs is None:
            return True
        return prefs.mail_forward_to_telegram

    async def _devices(
        self, notification: Notification, prefs: UserPreferences | None
    ) -> list[PushSubscription]:
        """The user's push devices, or none when push is off for the user."""
        if self.push is None or (prefs is not None and not prefs.notify_push):
            return []
        return await self.push.subscriptions(notification.user_id)

    def _no_channel_reason(self, prefs: UserPreferences | None) -> str:
        push_on = self.push is not None and (prefs is None or prefs.notify_push)
        return "no-channel" if push_on else "no-telegram"

    async def _send(
        self,
        notification: Notification,
        user: UserRef,
        accounts: Sequence[TelegramAccountRef],
        recipients: Sequence[TelegramAccountRef],
        devices: Sequence[PushSubscription],
    ) -> float | None:
        """Push first, so a Telegram flood pause does not hold the devices back."""
        pushed = PushRun()
        if self.push is not None and devices:
            pushed = await self.push.deliver(notification, user, devices)
        telegram = await self._telegram(notification, user, recipients)
        if telegram.retry_after is not None:
            await self._pause(notification, telegram.retry_after)
            return telegram.retry_after
        keys: list[DeliveryKey] = list(pushed.keys)
        if telegram.counts:
            keys += [a.telegram_user_id for a in accounts]
        if not keys:
            await self._skip(notification, telegram.skip_reason or "no-channel")
            return None
        notification.attempts += 1
        notification.error = "; ".join([*telegram.errors, *pushed.errors]) or None
        await self._settle(notification, keys)
        return None

    # - - - Telegram - - -

    async def _telegram(
        self,
        notification: Notification,
        user: UserRef,
        recipients: Sequence[TelegramAccountRef],
    ) -> _TelegramRun:
        """Render once and send to every account that has not got the message."""
        if not recipients:
            return _TelegramRun()
        renderer = self.renderers.get(notification.type)
        if renderer is None:
            return _TelegramRun(
                counts=False, skip_reason=f"no-renderer:{notification.type}"
            )
        ctx = RenderContext(
            user=user,
            locale=user.locale,
            telegram_user_id=recipients[0].telegram_user_id,
        )
        try:
            message = await renderer(notification.payload, ctx)
        except Exception as exc:  # one bad payload must not stop the whole batch
            log.exception("notification_render_failed", id=str(notification.id))
            for account in recipients:
                notification.record(account.telegram_user_id, DeliveryState.FAILED)
            return _TelegramRun(errors=[f"render-failed:{type(exc).__name__}"])
        if message is None:
            return _TelegramRun(counts=False, skip_reason="nothing-to-send")
        return await self._deliver(notification, message, recipients)

    async def _deliver(
        self,
        notification: Notification,
        message: RenderedMessage,
        recipients: Sequence[TelegramAccountRef],
    ) -> _TelegramRun:
        run = _TelegramRun()
        for account in recipients:
            chat_id = account.telegram_user_id
            try:
                note = await self._send_message(chat_id, message)
            except TelegramBlocked:
                notification.record(chat_id, DeliveryState.BLOCKED)
                await self.identity.set_telegram_blocked(chat_id, True)
            except TelegramRetryAfter as exc:
                run.retry_after = exc.seconds
                return run
            except TelegramSendFailed as exc:
                notification.record(chat_id, DeliveryState.FAILED)
                run.errors.append(f"{chat_id}:{exc}")
            else:
                notification.record(chat_id, DeliveryState.SENT)
                if note is not None:
                    run.errors.append(note)
        return run

    async def _send_message(self, chat_id: int, message: RenderedMessage) -> str | None:
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
        self, notification: Notification, keys: Sequence[DeliveryKey]
    ) -> None:
        settle(notification, keys, self.clock.now())
        await self._save(notification)

    async def _skip(self, notification: Notification, reason: str) -> None:
        skip(notification, reason)
        await self._save(notification)

    async def _pause(self, notification: Notification, seconds: float) -> None:
        """Flood control: put the row back without counting an attempt."""
        _reschedule(notification, self.clock.now() + timedelta(seconds=seconds))
        await self._save(notification)
