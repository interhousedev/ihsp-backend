"""SQL unit of work of the files module."""

from app.modules.files.infrastructure.repositories.file_repository import (
    SqlFileRepository,
)
from app.modules.files.infrastructure.repositories.file_share_repository import (
    SqlFileShareRepository,
)
from app.modules.files.ports.file_repository import FileRepository
from app.modules.files.ports.file_share_repository import FileShareRepository
from app.shared.db.uow import SqlUnitOfWork


class SqlFilesUnitOfWork(SqlUnitOfWork):
    """One transaction with the file repository (implements FilesUnitOfWork)."""

    files: FileRepository
    shares: FileShareRepository

    def _init_repos(self) -> None:
        """Create the repository bound to this transaction's session."""
        self.files = SqlFileRepository(self.session)
        self.shares = SqlFileShareRepository(self.session)
