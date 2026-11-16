"""The goal plan: dated milestones, optionally tied to an activity or honor."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Final, Literal
from uuid import UUID

from app.modules.admission.domain.errors import CharLimitError

GoalStatus = Literal["planned", "done", "dropped"]
GoalSource = Literal["ai", "manual"]

TITLE_MAX: Final = 120
MAX_MILESTONES: Final = 12


@dataclass(slots=True)
class GoalMilestone:
    """One step of the plan; `due_month` is the first day of its month."""

    id: UUID
    student_id: UUID
    title: str
    item_id: UUID | None = None
    due_month: date | None = None
    target_value: Decimal | None = None
    status: GoalStatus = "planned"
    done_at: datetime | None = None
    source: GoalSource = "manual"
    sort_order: int = 0
    lock_version: int = 0

    def validate(self) -> None:
        """Reject an empty or over-long title."""
        count = len(self.title)
        if not self.title or count > TITLE_MAX:
            raise CharLimitError(
                params={"field": "title", "limit": TITLE_MAX, "count": count}
            )
