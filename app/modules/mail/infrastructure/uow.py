"""SQL unit of work of the mail module."""

from app.modules.mail.infrastructure.repositories.mail_repository import (
    SqlMailRepository,
)
from app.modules.mail.ports.mail_repository import MailRepository
from app.shared.db.uow import SqlUnitOfWork


class SqlMailUnitOfWork(SqlUnitOfWork):
    """One transaction with the mail repository (implements MailUnitOfWork)."""

    mail: MailRepository

    def _init_repos(self) -> None:
        """Create the repository bound to this transaction's session."""
        self.mail = SqlMailRepository(self.session)
