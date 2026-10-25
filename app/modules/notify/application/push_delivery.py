"""The Web Push channel of the dispatcher: one notification to a user's devices."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from uuid import UUID

from app.modules.notify.application.push_message import build_push_payload
from app.modules.notify.domain.notification import Notification
from app.modules.notify.domain.notification_status import DeliveryState
from app.modules.notify.domain.push_errors import PushGone, PushSendFailed
from app.modules.notify.domain.push_subscription import (
    MAX_FAILURES,
    PushSubscription,
    push_delivery_key,
)
from app.modules.notify.ports.push_sender import PushSender
from app.modules.notify.ports.send_limiter import SendLimiter
from app.modules.notify.ports.unit_of_work import NotifyUnitOfWork
from app.settings import UrlsSettings
from app.shared.clock import Clock
from app.shared.contracts.identity import UserRef
from app.shared.i18n.core import I18nCore

import structlog

log = structlog.get_logger(__name__)


@dataclass(slots=True)
class PushRun:
    """What one pass over the devices did."""

    keys: list[str] = field(default_factory=list)
    """Delivery keys of the devices that still count (not dropped)."""
    errors: list[str] = field(default_factory=list)


@dataclass(slots=True)
class _Tally:
    succeeded: list[UUID] = field(default_factory=list)
    failed: list[UUID] = field(default_factory=list)
    gone: list[UUID] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class PushDelivery:
    """Sends a notification to every subscription, one message per device."""

    def __init__(
        self,
        *,
        uow_factory: Callable[[], NotifyUnitOfWork],
        sender: PushSender,
        limiter: SendLimiter,
        i18n: I18nCore,
        urls: UrlsSettings,
        clock: Clock,
    ) -> None:
        """Store the ports; a unit of work is created for every transaction."""
        self.uow_factory = uow_factory
        self.sender = sender
        self.limiter = limiter
        self.i18n = i18n
        self.urls = urls
        self.clock = clock

    async def subscriptions(self, user_id: UUID) -> list[PushSubscription]:
        """Return the user's devices."""
        async with self.uow_factory() as uow:
            return await uow.push_subscriptions.list_for_user(user_id)

    async def deliver(
        self,
        notification: Notification,
        user: UserRef,
        subscriptions: Sequence[PushSubscription],
    ) -> PushRun:
        """Send to the devices that have not got it yet and record each result."""
        todo = [
            s
            for s in subscriptions
            if not notification.delivered_to(push_delivery_key(s.id))
        ]
        tally = _Tally()
        if todo:
            await self._send_all(notification, user, todo, tally)
            await self._save(notification, tally)
        dropped = set(tally.gone)
        return PushRun(
            keys=[
                push_delivery_key(s.id) for s in subscriptions if s.id not in dropped
            ],
            errors=tally.errors,
        )

    async def _send_all(
        self,
        notification: Notification,
        user: UserRef,
        todo: Sequence[PushSubscription],
        tally: _Tally,
    ) -> None:
        try:
            body = build_push_payload(
                notification, user, i18n=self.i18n, urls=self.urls
            ).to_json()
        except Exception as exc:  # one bad payload must not stop the whole batch
            log.exception("push_render_failed", id=str(notification.id))
            for subscription in todo:
                notification.record(
                    push_delivery_key(subscription.id), DeliveryState.FAILED
                )
            tally.errors.append(f"push:render-failed:{type(exc).__name__}")
            return
        for subscription in todo:
            await self._send_one(notification, subscription, body, tally)

    async def _send_one(
        self,
        notification: Notification,
        subscription: PushSubscription,
        body: str,
        tally: _Tally,
    ) -> None:
        key = push_delivery_key(subscription.id)
        await self.limiter.acquire()
        try:
            await self.sender.send(subscription, body)
        except PushGone:
            tally.gone.append(subscription.id)
            notification.deliveries.pop(key, None)
        except PushSendFailed as exc:
            notification.record(key, DeliveryState.FAILED)
            tally.failed.append(subscription.id)
            tally.errors.append(f"push:{subscription.id.hex[:8]}:{exc}")
        else:
            notification.record(key, DeliveryState.SENT)
            tally.succeeded.append(subscription.id)

    async def _save(self, notification: Notification, tally: _Tally) -> None:
        """Update device bookkeeping; drop dead and chronically failing devices."""
        async with self.uow_factory() as uow:
            repo = uow.push_subscriptions
            await repo.record_success(tally.succeeded, self.clock.now())
            for subscription_id in tally.failed:
                if await repo.record_failure(subscription_id) >= MAX_FAILURES:
                    tally.gone.append(subscription_id)
                    notification.deliveries.pop(
                        push_delivery_key(subscription_id), None
                    )
            await repo.delete_many(tally.gone)
            await uow.commit()
