"""Unit of work port of the mail module."""

from collections.abc import Callable
from types import TracebackType
from typing import Protocol, Self

from app.modules.mail.ports.mail_repository import MailRepository
from app.shared.db.uow import AfterCommit
from app.shared.notifications import AuditDraft, NotificationDraft


class MailUnitOfWork(Protocol):
    """One transaction with the mail repository, outbox, audit and hooks."""

    mail: MailRepository

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

    def notify(self, *drafts: NotificationDraft) -> None:
        """Queue notifications for the outbox."""
        ...

    def audit(self, *drafts: AuditDraft) -> None:
        """Queue audit events."""
        ...

    def after_commit(self, hook: AfterCommit) -> None:
        """Run a coroutine after a successful commit."""
        ...

    async def commit(self) -> None:
        """Commit, then run the after-commit hooks."""
        ...


UowFactory = Callable[[], MailUnitOfWork]
