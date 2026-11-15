"""SQL unit of work of the legal module."""

from app.modules.legal.infrastructure.repositories.legal_repository import (
    SqlLegalRepository,
)
from app.shared.db.uow import SqlUnitOfWork


class SqlLegalUnitOfWork(SqlUnitOfWork):
    """One transaction over legal documents and acceptances."""

    legal: SqlLegalRepository

    def _init_repos(self) -> None:
        """Create the repository on the open session."""
        self.legal = SqlLegalRepository(self.session)
