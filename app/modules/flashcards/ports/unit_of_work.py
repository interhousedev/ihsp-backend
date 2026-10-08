"""Port: one transaction over sets and cards."""

from collections.abc import Callable
from types import TracebackType
from typing import Protocol, Self

from app.modules.flashcards.ports.card_repository import FlashcardRepository
from app.modules.flashcards.ports.set_repository import FlashcardSetRepository


class FlashcardsUnitOfWork(Protocol):
    """Opens a transaction on entry; commit() commits it."""

    @property
    def sets(self) -> FlashcardSetRepository:
        """Sets of the open transaction."""
        ...

    @property
    def cards(self) -> FlashcardRepository:
        """Cards of the open transaction."""
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


UowFactory = Callable[[], FlashcardsUnitOfWork]
