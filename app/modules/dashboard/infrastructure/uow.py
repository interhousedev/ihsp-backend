"""SQL unit of work of the dashboard module."""

from app.modules.dashboard.infrastructure.repositories.layout_repository import (
    SqlLayoutRepository,
)
from app.shared.db.uow import SqlUnitOfWork


class SqlDashboardUnitOfWork(SqlUnitOfWork):
    """One transaction over dashboard layouts."""

    layouts: SqlLayoutRepository

    def _init_repos(self) -> None:
        """Create the repositories on the open session."""
        self.layouts = SqlLayoutRepository(self.session)
