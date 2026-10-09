"""Statuses of a notification and of its delivery to one account or device."""

from enum import StrEnum


class NotificationStatus(StrEnum):
    """Delivery of a notification as a whole, over Telegram and push."""

    PENDING = "pending"
    SENDING = "sending"
    SENT = "sent"
    PARTIAL = "partial"
    FAILED = "failed"
    SKIPPED = "skipped"


class DeliveryState(StrEnum):
    """Result of sending to one linked Telegram account or one push device."""

    SENT = "sent"
    FAILED = "failed"
    BLOCKED = "blocked"


DeliveryKey = int | str
"""Who a delivery went to: a Telegram user id, or `push:<subscription id>`."""

OPEN_STATUSES = frozenset(
    {
        NotificationStatus.PENDING,
        NotificationStatus.SENDING,
        NotificationStatus.PARTIAL,
    }
)
"""Statuses of a notification that Telegram delivery has not finished yet."""
