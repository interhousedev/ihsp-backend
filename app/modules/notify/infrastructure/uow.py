"""SQL unit of work of the notify module."""

from app.modules.notify.infrastructure.repositories.course_broadcast_repository import (  # noqa: E501
    SqlCourseBroadcastRepository,
)
from app.modules.notify.infrastructure.repositories.notification_repository import (
    SqlNotificationRepository,
)
from app.modules.notify.infrastructure.repositories.push_subscription_repository import (  # noqa: E501
    SqlPushSubscriptionRepository,
)
from app.shared.db.uow import SqlUnitOfWork


class SqlNotifyUnitOfWork(SqlUnitOfWork):
    """One transaction over the notification and push subscription repositories."""

    notifications: SqlNotificationRepository
    push_subscriptions: SqlPushSubscriptionRepository
    course_broadcasts: SqlCourseBroadcastRepository

    def _init_repos(self) -> None:
        """Create the repositories bound to this transaction's session."""
        self.notifications = SqlNotificationRepository(self.session)
        self.push_subscriptions = SqlPushSubscriptionRepository(self.session)
        self.course_broadcasts = SqlCourseBroadcastRepository(self.session)
