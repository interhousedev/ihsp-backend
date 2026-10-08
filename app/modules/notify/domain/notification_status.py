"""Statuses of a notification and of its delivery to one Telegram account."""

from enum import StrEnum


class NotificationStatus(StrEnum):
    """Telegram delivery of a notification as a whole (README → Notification)."""

    PENDING = "pending"
    SENDING = "sending"
    SENT = "sent"
    PARTIAL = "partial"
    FAILED = "failed"
    SKIPPED = "skipped"


class DeliveryState(StrEnum):
    """Result of sending to one linked Telegram account."""

    SENT = "sent"
    FAILED = "failed"
    BLOCKED = "blocked"


OPEN_STATUSES = frozenset(
    {
        NotificationStatus.PENDING,
        NotificationStatus.SENDING,
        NotificationStatus.PARTIAL,
    }
)
"""Statuses of a notification that Telegram delivery has not finished yet."""
