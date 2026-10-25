"""SQL unit of work of the admin module."""

from app.modules.admin.infrastructure.repositories.broadcast_repository import (
    SqlBroadcastRepository,
)
from app.modules.admin.infrastructure.repositories.delivery_reader import (
    SqlDeliveryReader,
)
from app.modules.admin.infrastructure.repositories.limit_store import SqlLimitStore
from app.shared.db.uow import SqlUnitOfWork


class SqlAdminUnitOfWork(SqlUnitOfWork):
    """One transaction over broadcasts and runtime limits, with outbox and audit."""

    broadcasts: SqlBroadcastRepository
    deliveries: SqlDeliveryReader
    limit_store: SqlLimitStore

    def _init_repos(self) -> None:
        """Create the repositories bound to this transaction's session."""
        self.broadcasts = SqlBroadcastRepository(self.session)
        self.deliveries = SqlDeliveryReader(self.session)
        self.limit_store = SqlLimitStore(self.session)
