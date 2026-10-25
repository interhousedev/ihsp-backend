"""SQL unit of work of the links module."""

from app.modules.links.infrastructure.repositories.link_repository import (
    SqlLinkRepository,
)
from app.shared.db.uow import SqlUnitOfWork


class LinksSqlUnitOfWork(SqlUnitOfWork):
    """One transaction with the links repository, outbox and audit."""

    links: SqlLinkRepository

    def _init_repos(self) -> None:
        """Create the repository bound to the session."""
        self.links = SqlLinkRepository(self.session)
