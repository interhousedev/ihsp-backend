"""Port: one transaction over dashboard layouts."""

from collections.abc import Callable
from types import TracebackType
from typing import Protocol, Self

from app.modules.dashboard.ports.layout_repository import LayoutRepository


class DashboardUnitOfWork(Protocol):
    """Opens a transaction on entry; commit() commits it."""

    @property
    def layouts(self) -> LayoutRepository:
        """Layouts of the open transaction."""
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


UowFactory = Callable[[], DashboardUnitOfWork]
