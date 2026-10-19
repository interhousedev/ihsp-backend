"""SQL unit of work of the knowledge module."""

from app.modules.knowledge.infrastructure.repositories.entry_repository import (
    SqlEntryRepository,
)
from app.shared.db.uow import SqlUnitOfWork


class SqlKnowledgeUnitOfWork(SqlUnitOfWork):
    """One transaction over knowledge entries."""

    entries: SqlEntryRepository

    def _init_repos(self) -> None:
        """Create the repository on the open session."""
        self.entries = SqlEntryRepository(self.session)
