"""Unit of work of the EMIS use cases."""

from app.modules.identity.infrastructure.repositories.registration_repository import (
    RegistrationRepository,
)
from app.shared.db.uow import SqlUnitOfWork


class EmisSqlUnitOfWork(SqlUnitOfWork):
    """One transaction with the account repository, outbox and audit."""

    accounts: RegistrationRepository

    def _init_repos(self) -> None:
        """Bind the repository to this transaction's session."""
        self.accounts = RegistrationRepository(self.session)
