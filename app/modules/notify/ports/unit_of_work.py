"""Unit of work port of the notify module."""

from types import TracebackType
from typing import Protocol, Self

from app.modules.notify.ports.course_broadcast_repository import (
    CourseBroadcastRepository,
)
from app.modules.notify.ports.notification_repository import NotificationRepository
from app.modules.notify.ports.push_subscription_repository import (
    PushSubscriptionRepository,
)
from app.shared.notifications import NotificationDraft


class NotifyUnitOfWork(Protocol):
    """One transaction over the notify repositories."""

    @property
    def notifications(self) -> NotificationRepository:
        """Notification repository bound to this transaction."""
        ...

    @property
    def push_subscriptions(self) -> PushSubscriptionRepository:
        """Web Push subscription repository bound to this transaction."""
        ...

    @property
    def course_broadcasts(self) -> CourseBroadcastRepository:
        """Course broadcast history bound to this transaction."""
        ...

    def notify(self, *drafts: NotificationDraft) -> None:
        """Queue notifications to insert at commit."""
        ...

    async def __aenter__(self) -> Self:
        """Open the transaction."""
        ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Roll back unless committed and release the session."""
        ...

    async def commit(self) -> None:
        """Commit the transaction."""
        ...
