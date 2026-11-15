"""Unit of work of the EMIS use cases."""

from app.modules.identity.infrastructure.repositories.registration_repository import (
    RegistrationRepository,
)
from app.shared.contracts.legal import ConsentDraft, ConsentWriter
from app.shared.db.uow import AfterCommit, AuditWriter, OutboxWriter, SqlUnitOfWork

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class EmisSqlUnitOfWork(SqlUnitOfWork):
    """One transaction with the account repository, outbox, audit and consent."""

    accounts: RegistrationRepository

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        outbox_writer: OutboxWriter,
        audit_writer: AuditWriter,
        outbox_committed_hook: AfterCommit | None = None,
        consent_writer: ConsentWriter | None = None,
    ) -> None:
        """Store the factories and the optional legal acceptance writer."""
        super().__init__(
            sessionmaker, outbox_writer, audit_writer, outbox_committed_hook
        )
        self._consent_writer = consent_writer
        self._consent: list[ConsentDraft] = []

    def _init_repos(self) -> None:
        """Bind the repository to this transaction's session."""
        self.accounts = RegistrationRepository(self.session)
        self._consent = []

    def consent(self, *drafts: ConsentDraft) -> None:
        """Queue legal acceptances for the commit."""
        self._consent.extend(drafts)

    async def commit(self) -> None:
        """Write the acceptances in the same transaction, then commit."""
        if self._consent and self._consent_writer is not None:
            await self._consent_writer(self.session, self._consent)
        self._consent = []
        await super().commit()
