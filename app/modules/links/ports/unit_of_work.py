"""Unit of work port of the links module."""

from collections.abc import Callable
from types import TracebackType
from typing import Protocol, Self

from app.modules.links.ports.link_repository import LinkRepository
from app.shared.db.uow import AfterCommit
from app.shared.notifications import AuditDraft, NotificationDraft


class LinksUnitOfWork(Protocol):
    """One transaction with the links repository, outbox and audit."""

    @property
    def links(self) -> LinkRepository:
        """Return the link repository of this transaction."""
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
        """Commit and run the after-commit hooks."""
        ...

    def notify(self, *drafts: NotificationDraft) -> None:
        """Queue notifications for the outbox."""
        ...

    def audit(self, *drafts: AuditDraft) -> None:
        """Queue audit events."""
        ...

    def after_commit(self, hook: AfterCommit) -> None:
        """Run a coroutine after a successful commit."""
        ...


UowFactory = Callable[[], LinksUnitOfWork]
