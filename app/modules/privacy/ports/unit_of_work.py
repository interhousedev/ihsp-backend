"""Port: one transaction over erasure requests and exports."""

from collections.abc import Awaitable, Callable
from types import TracebackType
from typing import Protocol, Self

from app.modules.privacy.ports.repositories import ErasureRepository, ExportRepository
from app.shared.notifications import AuditDraft, NotificationDraft


class PrivacyUnitOfWork(Protocol):
    """Opens a transaction on entry; commit() commits it, the notices and the audit."""

    @property
    def erasure(self) -> ErasureRepository:
        """Erasure requests."""
        ...

    @property
    def exports(self) -> ExportRepository:
        """Data exports."""
        ...

    def notify(self, *drafts: NotificationDraft) -> None:
        """Queue notifications to insert at commit."""
        ...

    def audit(self, *drafts: AuditDraft) -> None:
        """Queue audit events to insert at commit."""
        ...

    def after_commit(self, hook: Callable[[], Awaitable[None]]) -> None:
        """Run a coroutine after a successful commit."""
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


UowFactory = Callable[[], PrivacyUnitOfWork]
