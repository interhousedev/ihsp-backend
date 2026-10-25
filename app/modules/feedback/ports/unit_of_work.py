"""Port: one transaction over feedback, with the notification outbox."""

from collections.abc import Callable
from types import TracebackType
from typing import Protocol, Self

from app.modules.feedback.ports.feedback_repository import FeedbackRepository
from app.shared.notifications import NotificationDraft


class FeedbackUnitOfWork(Protocol):
    """Opens a transaction on entry; commit() commits it and the outbox."""

    @property
    def feedback(self) -> FeedbackRepository:
        """Feedback of the open transaction."""
        ...

    def notify(self, *drafts: NotificationDraft) -> None:
        """Queue notifications to insert at commit."""
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


UowFactory = Callable[[], FeedbackUnitOfWork]
