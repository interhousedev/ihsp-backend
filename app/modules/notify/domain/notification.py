"""The notification entity: one row of the bot outbox and of the web inbox."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from app.modules.notify.domain.notification_status import (
    DeliveryKey,
    DeliveryState,
    NotificationStatus,
)
from app.shared.notifications import NotificationType


@dataclass(slots=True)
class Notification:
    """A notification for one user with its Telegram and push delivery state."""

    id: UUID
    user_id: UUID
    type: NotificationType
    payload: dict[str, Any]
    dedupe_key: str
    scheduled_at: datetime
    created_at: datetime
    broadcast_id: UUID | None = None
    status: NotificationStatus = NotificationStatus.PENDING
    deliveries: dict[DeliveryKey, DeliveryState] = field(default_factory=dict)
    attempts: int = 0
    next_attempt_at: datetime | None = None
    sent_at: datetime | None = None
    read_at: datetime | None = None
    error: str | None = None

    def delivered_to(self, key: DeliveryKey) -> bool:
        """Return True if this Telegram account or device already got the message."""
        return self.deliveries.get(key) == DeliveryState.SENT

    def record(self, key: DeliveryKey, state: DeliveryState) -> None:
        """Remember the result for one Telegram account or push device."""
        self.deliveries[key] = state
