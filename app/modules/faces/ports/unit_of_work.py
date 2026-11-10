"""Port: one transaction over faces, with the notification outbox."""

from collections.abc import Callable
from types import TracebackType
from typing import Protocol, Self

from app.modules.faces.ports.repositories import (
    ActivityRepository,
    DeviceRepository,
    ProfileRepository,
)
from app.shared.notifications import NotificationDraft


class FacesUnitOfWork(Protocol):
    """Opens a transaction on entry; commit() commits it and the outbox."""

    @property
    def profiles(self) -> ProfileRepository:
        """Face profiles of the open transaction."""
        ...

    @property
    def devices(self) -> DeviceRepository:
        """Devices of the open transaction."""
        ...

    @property
    def activity(self) -> ActivityRepository:
        """Calls and passages of the open transaction."""
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


UowFactory = Callable[[], FacesUnitOfWork]
