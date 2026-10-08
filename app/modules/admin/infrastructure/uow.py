"""SQL unit of work of the admin module."""

from app.modules.admin.infrastructure.repositories.broadcast_repository import (
    SqlBroadcastRepository,
)
from app.modules.admin.infrastructure.repositories.delivery_reader import (
    SqlDeliveryReader,
)
from app.shared.db.uow import SqlUnitOfWork


class SqlAdminUnitOfWork(SqlUnitOfWork):
    """One transaction over broadcasts, with outbox and audit."""

    broadcasts: SqlBroadcastRepository
    deliveries: SqlDeliveryReader

    def _init_repos(self) -> None:
        """Create the repositories bound to this transaction's session."""
        self.broadcasts = SqlBroadcastRepository(self.session)
        self.deliveries = SqlDeliveryReader(self.session)
