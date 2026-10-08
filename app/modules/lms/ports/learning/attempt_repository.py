"""Port: test attempts."""

from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.modules.lms.domain.learning.entities import Attempt


class AttemptRepository(Protocol):
    """Attempts at test blocks."""

    async def add(self, attempt: Attempt) -> None:
        """Insert an attempt.

        Raises:
            AttemptNumberTakenError: The (user, step, block, attempt_no) is taken.
        """
        ...

    async def get(
        self, attempt_id: UUID, *, for_update: bool = False
    ) -> Attempt | None:
        """Return an attempt, optionally locking its row."""
        ...

    async def save(self, attempt: Attempt) -> None:
        """Store answers, result and review fields of the attempt."""
        ...

    async def list_for_step(self, user_id: UUID, step_id: UUID) -> list[Attempt]:
        """Return the user's non-preview attempts in a step ordered by number."""
        ...

    async def list_open(
        self, user_id: UUID, step_id: UUID, *, preview: bool
    ) -> list[Attempt]:
        """Return the user's unsubmitted attempts in a step, newest first."""
        ...

    async def count(self, user_id: UUID, step_id: UUID, block_id: str) -> int:
        """Return how many non-preview attempts the user started in the block."""
        ...

    async def max_attempt_no(
        self, user_id: UUID, step_id: UUID, block_id: str, *, preview: bool
    ) -> int:
        """Return the highest attempt number used so far (0 if none)."""
        ...

    async def last_submitted_at(
        self, user_id: UUID, step_id: UUID, block_id: str
    ) -> datetime | None:
        """Return when the user last submitted a non-preview attempt in the block."""
        ...

    async def passed_block_ids(self, user_id: UUID, step_id: UUID) -> set[str]:
        """Return the test blocks of the step with a passed non-preview attempt."""
        ...

    async def list_submitted_for_course(self, course_id: UUID) -> list[Attempt]:
        """Return all submitted non-preview attempts in the course."""
        ...
