"""Port: activities, honors, their metrics, interviews and item reviews."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal, Protocol
from uuid import UUID

from app.modules.admission.domain.items import Item, ItemGrade

Horizon = Literal["current", "projected"]
Provenance = Literal["self_stated", "source_supported", "independently_verified"]
SafetyFlag = Literal["none", "injection_suspected", "safeguarding"]
ReviewStatus = Literal["ready", "in_flight", "failed"]
FeedbackKind = Literal["unfair", "helpful"]


@dataclass(frozen=True, slots=True)
class Metric:
    """A number of an item; `projected` ones are plans with a target date."""

    id: UUID
    item_id: UUID
    label: str
    value: Decimal
    unit: str | None
    horizon: Horizon
    as_of: date | None = None
    target_date: date | None = None
    provenance: Provenance = "self_stated"


@dataclass(frozen=True, slots=True)
class InterviewRound:
    """One round of the item interview: the questions and the student's answers."""

    id: UUID
    item_id: UUID
    round: int
    questions: dict[str, Any]
    answers: dict[str, Any] = field(default_factory=dict)
    created_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class StoredReview:
    """A review row; `input_hash` is the cache key."""

    id: UUID
    student_id: UUID
    target_kind: str
    target_id: UUID
    input_hash: str
    task: str
    model: str | None
    prompt_version: str
    rubric_version: str | None
    schema_version: str
    words_version: int | None
    grades: dict[str, Any]
    overall: str | None
    payload: dict[str, Any]
    safety_flag: SafetyFlag
    status: ReviewStatus
    created_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class ProfileWordsRef:
    """The student's confirmed words and their version."""

    words: tuple[str, ...]
    version: int


class ItemRepository(Protocol):
    """Stored items with their metrics, interviews and reviews."""

    async def list_for(self, student_id: UUID) -> list[Item]:
        """Return the student's items in display order."""
        ...

    async def get(self, item_id: UUID) -> Item | None:
        """Return one item."""
        ...

    async def add(self, item: Item) -> Item:
        """Insert an item; returns it with id, time and version."""
        ...

    async def update(self, item: Item) -> Item:
        """Store the fields and bump the lock version."""
        ...

    async def delete(self, item_id: UUID) -> None:
        """Delete the item with its metrics, interviews and proofs."""
        ...

    async def set_order(self, ordered: Sequence[UUID]) -> None:
        """Set the sort order of the given items to their list position."""
        ...

    async def set_grade(self, item_id: UUID, grade: ItemGrade) -> None:
        """Store the AI grade of the item; the lock version stays."""
        ...

    async def metrics_for(self, item_ids: Sequence[UUID]) -> dict[UUID, list[Metric]]:
        """Return the metrics of the items."""
        ...

    async def replace_metrics(self, item_id: UUID, metrics: Sequence[Metric]) -> None:
        """Replace the metrics of an item."""
        ...

    async def interviews(self, item_id: UUID) -> list[InterviewRound]:
        """Return the interview rounds of an item, oldest first."""
        ...

    async def add_interview(self, round_: InterviewRound) -> InterviewRound:
        """Insert an interview round."""
        ...

    async def update_round(
        self,
        round_id: UUID,
        *,
        questions: dict[str, Any] | None = None,
        answers: dict[str, Any] | None = None,
    ) -> None:
        """Update the questions and/or answers of a round (None keeps the value)."""
        ...

    async def clear_interviews(self, item_id: UUID) -> None:
        """Delete the interview rounds of an item (restart)."""
        ...

    async def words(self, student_id: UUID) -> ProfileWordsRef | None:
        """Return the student's words, or None if none are set."""
        ...

    async def find_review(
        self, target_kind: str, target_id: UUID, input_hash: str
    ) -> StoredReview | None:
        """Return the review stored for the same input."""
        ...

    async def latest_review(
        self, target_kind: str, target_id: UUID
    ) -> StoredReview | None:
        """Return the newest ready review of a target."""
        ...

    async def get_review(self, review_id: UUID) -> StoredReview | None:
        """Return one review."""
        ...

    async def add_review(self, review: StoredReview) -> StoredReview:
        """Insert a review."""
        ...

    async def count_reviews(
        self, student_id: UUID, task: str, since: datetime, *, target_id: UUID | None
    ) -> int:
        """Count reviews of a task since a time, optionally of one target."""
        ...

    async def add_feedback(
        self, review_id: UUID, student_id: UUID, kind: FeedbackKind, note: str | None
    ) -> None:
        """Store the student's feedback on a review."""
        ...
