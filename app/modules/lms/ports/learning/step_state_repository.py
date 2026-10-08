"""Port: a student's progress in steps and flash cards."""

from collections.abc import Sequence
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from app.modules.lms.domain.learning.entities import StepState


class StepStateRepository(Protocol):
    """Per-student step state, keyed by the stable step id."""

    async def get(self, user_id: UUID, step_id: UUID) -> StepState | None:
        """Return the state of a step for a user."""
        ...

    async def completed_step_ids(
        self, user_id: UUID, step_ids: Sequence[UUID]
    ) -> set[UUID]:
        """Return which of the steps the user has completed."""
        ...

    async def touch_viewed(
        self, user_id: UUID, step_id: UUID, *, now: datetime, complete: bool
    ) -> StepState:
        """Record a view; with ``complete`` also complete the step (once)."""
        ...

    async def set_completed(
        self, user_id: UUID, step_id: UUID, *, now: datetime
    ) -> None:
        """Complete the step if it is not completed yet."""
        ...

    async def clear_completed(self, user_id: UUID, step_id: UUID) -> None:
        """Mark the step as not completed (after a reviewer lowered a score)."""
        ...

    async def save_card(
        self,
        user_id: UUID,
        step_id: UUID,
        card_id: str,
        state: dict[str, Any],
        *,
        now: datetime,
    ) -> None:
        """Replace the scheduling state of one card, leaving the others as they are."""
        ...
