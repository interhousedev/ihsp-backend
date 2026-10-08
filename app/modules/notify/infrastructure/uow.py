"""SQL unit of work of the notify module."""

from app.modules.notify.infrastructure.repositories.notification_repository import (
    SqlNotificationRepository,
)
from app.shared.db.uow import SqlUnitOfWork


class SqlNotifyUnitOfWork(SqlUnitOfWork):
    """One transaction over the notification repository."""

    notifications: SqlNotificationRepository

    def _init_repos(self) -> None:
        """Create the repository bound to this transaction's session."""
        self.notifications = SqlNotificationRepository(self.session)
