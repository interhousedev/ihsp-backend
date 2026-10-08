"""Unit of work port of the admin module."""

from types import TracebackType
from typing import Protocol, Self

from app.modules.admin.ports.broadcast_repository import BroadcastRepository
from app.modules.admin.ports.delivery_reader import DeliveryReader
from app.shared.notifications import AuditDraft, NotificationDraft


class AdminUnitOfWork(Protocol):
    """One transaction over the admin repositories, with outbox and audit."""

    @property
    def broadcasts(self) -> BroadcastRepository:
        """Broadcast repository bound to this transaction."""
        ...

    @property
    def deliveries(self) -> DeliveryReader:
        """Delivery counts read from the notifications of a broadcast."""
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

    def notify(self, *drafts: NotificationDraft) -> None:
        """Queue notifications to write at commit."""
        ...

    def audit(self, *drafts: AuditDraft) -> None:
        """Queue audit events to write at commit."""
        ...

    async def commit(self) -> None:
        """Write the outbox and audit rows and commit."""
        ...
