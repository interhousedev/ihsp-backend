"""Port: the stable identity of steps."""

from typing import Protocol
from uuid import UUID

from app.modules.lms.domain.learning.entities import LearningStep


class StepRepository(Protocol):
    """Steps of courses."""

    async def get(self, step_id: UUID) -> LearningStep | None:
        """Return a step by id."""
        ...
