"""Port: one running question per notebook and student."""

from contextlib import AbstractAsyncContextManager
from typing import Protocol
from uuid import UUID


class TurnLock(Protocol):
    """Keeps two questions of one student in one notebook from running together."""

    def hold(
        self, notebook_id: UUID, user_id: UUID
    ) -> AbstractAsyncContextManager[None]:
        """Hold the lock; raise `BusyError` if it is taken."""
        ...
