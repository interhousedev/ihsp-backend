"""Port: one transaction over legal documents, with the audit trail."""

from collections.abc import Callable
from types import TracebackType
from typing import Protocol, Self

from app.modules.legal.ports.repositories import LegalRepository
from app.shared.notifications import AuditDraft


class LegalUnitOfWork(Protocol):
    """Opens a transaction on entry; commit() commits it and the audit."""

    @property
    def legal(self) -> LegalRepository:
        """Legal documents and acceptances."""
        ...

    def audit(self, *drafts: AuditDraft) -> None:
        """Queue audit events to insert at commit."""
        ...

    async def __aenter__(self) -> Self:
        """Open the transaction."""
        ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Roll back unless committed."""
        ...

    async def commit(self) -> None:
        """Commit the transaction."""
        ...


UowFactory = Callable[[], LegalUnitOfWork]
