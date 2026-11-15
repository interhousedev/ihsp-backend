"""Port: one transaction over onboarding progress."""

from collections.abc import Callable
from types import TracebackType
from typing import Protocol, Self

from app.modules.onboarding.ports.repositories import ProgressRepository


class OnboardingUnitOfWork(Protocol):
    """Opens a transaction on entry; commit() commits it."""

    @property
    def progress(self) -> ProgressRepository:
        """Progress rows of the open transaction."""
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


UowFactory = Callable[[], OnboardingUnitOfWork]
