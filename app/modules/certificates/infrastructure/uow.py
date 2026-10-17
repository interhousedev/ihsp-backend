"""SQL unit of work of the certificates module."""

from app.modules.certificates.infrastructure.repositories.entry_repository import (
    SqlEntryRepository,
)
from app.modules.certificates.infrastructure.repositories.type_repository import (
    SqlCertificateTypeRepository,
)
from app.shared.db.uow import SqlUnitOfWork


class SqlCertificatesUnitOfWork(SqlUnitOfWork):
    """One transaction over types and entries."""

    types: SqlCertificateTypeRepository
    entries: SqlEntryRepository

    def _init_repos(self) -> None:
        """Create the repositories on the open session."""
        self.types = SqlCertificateTypeRepository(self.session)
        self.entries = SqlEntryRepository(self.session)
