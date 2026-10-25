"""Port: one running turn per chat."""

from contextlib import AbstractAsyncContextManager
from typing import Protocol
from uuid import UUID


class TurnLock(Protocol):
    """Keeps two requests from working on the same chat at the same time."""

    def hold(self, chat_id: UUID) -> AbstractAsyncContextManager[None]:
        """Hold the chat's lock; raise TurnInProgressError if it is taken."""
        ...
