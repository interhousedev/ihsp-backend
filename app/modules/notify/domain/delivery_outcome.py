"""Pure rules that turn per-account delivery results into the notification status."""

from collections.abc import Sequence
from datetime import datetime

from app.modules.notify.domain.notification import Notification
from app.modules.notify.domain.notification_status import (
    DeliveryKey,
    DeliveryState,
    NotificationStatus,
)
from app.modules.notify.domain.retry_policy import next_retry_at


def skip(notification: Notification, reason: str) -> None:
    """Close the notification without sending anything."""
    notification.status = NotificationStatus.SKIPPED
    notification.next_attempt_at = None
    notification.error = reason


def schedule_retry(notification: Notification, now: datetime) -> None:
    """Retry later after 1, 5 and 30 minutes; fail when the retries are used up."""
    retry_at = next_retry_at(notification.attempts, now)
    if retry_at is None:
        notification.status = NotificationStatus.FAILED
        notification.next_attempt_at = None
    else:
        notification.status = NotificationStatus.PARTIAL
        notification.next_attempt_at = retry_at


def settle(
    notification: Notification, account_ids: Sequence[DeliveryKey], now: datetime
) -> None:
    """Set the final status after a send round over the user's accounts and devices.

    Blocked accounts don't count. Everything else sent: `sent`. Only blocked
    accounts: `skipped`. Otherwise the failed accounts are retried.
    """
    live = [
        notification.deliveries.get(account_id)
        for account_id in account_ids
        if notification.deliveries.get(account_id) != DeliveryState.BLOCKED
    ]
    if not live:
        skip(notification, notification.error or "blocked")
    elif all(state == DeliveryState.SENT for state in live):
        notification.status = NotificationStatus.SENT
        notification.sent_at = now
        notification.next_attempt_at = None
    else:
        schedule_retry(notification, now)
