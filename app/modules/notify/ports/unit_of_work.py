"""Unit of work port of the notify module."""

from types import TracebackType
from typing import Protocol, Self

from app.modules.notify.ports.notification_repository import NotificationRepository


class NotifyUnitOfWork(Protocol):
    """One transaction over the notify repositories."""

    @property
    def notifications(self) -> NotificationRepository:
        """Notification repository bound to this transaction."""
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
        """Roll back unless committed and release the session."""
        ...

    async def commit(self) -> None:
        """Commit the transaction."""
        ...
