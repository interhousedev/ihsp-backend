"""SQL unit of work of the privacy module."""

from app.modules.privacy.infrastructure.repositories.sql import (
    SqlErasureRepository,
    SqlExportRepository,
)
from app.shared.db.uow import SqlUnitOfWork


class SqlPrivacyUnitOfWork(SqlUnitOfWork):
    """One transaction over erasure requests and exports."""

    erasure: SqlErasureRepository
    exports: SqlExportRepository

    def _init_repos(self) -> None:
        """Create the repositories on the open session."""
        self.erasure = SqlErasureRepository(self.session)
        self.exports = SqlExportRepository(self.session)
