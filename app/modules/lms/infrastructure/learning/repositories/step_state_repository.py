"""SQLAlchemy repository of step states (a student's progress in steps)."""

import json
from collections.abc import Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from app.modules.lms.domain.learning.entities import StepState
from app.modules.lms.infrastructure.orm.step_state import StepState as StepStateRow
from app.shared.ids import new_id

from sqlalchemy import ARRAY, Text, func, select, update
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.expression import cast, literal


def _to_entity(row: StepStateRow) -> StepState:
    """Map the ORM row to the entity."""
    return StepState(
        user_id=row.user_id,
        step_id=row.step_id,
        viewed_at=row.viewed_at,
        completed_at=row.completed_at,
        cards=dict(row.cards or {}),
    )


class SqlStepStateRepository:
    """Step states of the lms schema; rows are keyed by (user, stable step id)."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind to a session."""
        self.session = session

    async def get(self, user_id: UUID, step_id: UUID) -> StepState | None:
        """Return the state of a step for a user."""
        row = await self.session.scalar(
            select(StepStateRow)
            .where(StepStateRow.user_id == user_id, StepStateRow.step_id == step_id)
            .execution_options(populate_existing=True)
        )
        return _to_entity(row) if row else None

    async def cards_by_step(
        self, user_id: UUID, step_ids: Sequence[UUID]
    ) -> dict[UUID, dict[str, Any]]:
        """Return the stored cards and block results of the user per step."""
        if not step_ids:
            return {}
        rows = await self.session.execute(
            select(StepStateRow.step_id, StepStateRow.cards).where(
                StepStateRow.user_id == user_id, StepStateRow.step_id.in_(step_ids)
            )
        )
        return {step_id: dict(cards or {}) for step_id, cards in rows}

    async def completed_step_ids(
        self, user_id: UUID, step_ids: Sequence[UUID]
    ) -> set[UUID]:
        """Return which of the steps the user has completed."""
        if not step_ids:
            return set()
        rows = await self.session.scalars(
            select(StepStateRow.step_id).where(
                StepStateRow.user_id == user_id,
                StepStateRow.step_id.in_(step_ids),
                StepStateRow.completed_at.is_not(None),
            )
        )
        return set(rows)

    async def touch_viewed(
        self, user_id: UUID, step_id: UUID, *, now: datetime, complete: bool
    ) -> StepState:
        """Record a view; with ``complete`` also complete the step (once)."""
        statement = insert(StepStateRow).values(
            id=new_id(),
            user_id=user_id,
            step_id=step_id,
            viewed_at=now,
            completed_at=now if complete else None,
        )
        await self.session.execute(
            statement.on_conflict_do_update(
                index_elements=["user_id", "step_id"],
                set_={
                    "viewed_at": now,
                    "completed_at": func.coalesce(
                        StepStateRow.completed_at, statement.excluded.completed_at
                    ),
                },
            )
        )
        state = await self.get(user_id, step_id)
        if state is None:  # pragma: no cover - the upsert above guarantees the row
            raise LookupError("step state vanished")
        return state

    async def set_completed(
        self, user_id: UUID, step_id: UUID, *, now: datetime
    ) -> None:
        """Complete the step if it is not completed yet."""
        statement = insert(StepStateRow).values(
            id=new_id(),
            user_id=user_id,
            step_id=step_id,
            viewed_at=now,
            completed_at=now,
        )
        await self.session.execute(
            statement.on_conflict_do_update(
                index_elements=["user_id", "step_id"],
                set_={
                    "completed_at": func.coalesce(
                        StepStateRow.completed_at, statement.excluded.completed_at
                    )
                },
            )
        )

    async def clear_completed(self, user_id: UUID, step_id: UUID) -> None:
        """Mark the step as not completed (after a reviewer lowered a score)."""
        await self.session.execute(
            update(StepStateRow)
            .where(StepStateRow.user_id == user_id, StepStateRow.step_id == step_id)
            .values(completed_at=None)
            .execution_options(synchronize_session=False)
        )

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
        await self.session.execute(
            insert(StepStateRow)
            .values(id=new_id(), user_id=user_id, step_id=step_id, viewed_at=now)
            .on_conflict_do_nothing(index_elements=["user_id", "step_id"])
        )
        await self.session.execute(
            update(StepStateRow)
            .where(StepStateRow.user_id == user_id, StepStateRow.step_id == step_id)
            .values(
                cards=func.jsonb_set(
                    StepStateRow.cards,
                    literal([card_id], type_=ARRAY(Text)),
                    cast(literal(json.dumps(state)), JSONB),
                    True,
                )
            )
            .execution_options(synchronize_session=False)
        )
