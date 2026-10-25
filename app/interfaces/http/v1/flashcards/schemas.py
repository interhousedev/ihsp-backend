"""Request and response models of the flash card endpoints (names = API contract)."""

from datetime import date, datetime
from typing import Literal, Self
from uuid import UUID

from app.modules.flashcards.application.views import (
    ReviewStatsView,
    SetDetailView,
    SetItemView,
    StudyNextView,
)
from app.modules.flashcards.domain.limits import (
    CARD_TEXT_MAX,
    CARD_TEXT_MIN,
    DESCRIPTION_MAX,
    MAX_CARDS_PER_SET,
    NEW_PER_DAY_MAX,
    NEW_PER_DAY_MIN,
    REVIEWS_PER_DAY_MAX,
    REVIEWS_PER_DAY_MIN,
    TITLE_MAX,
    TITLE_MIN,
)

from pydantic import BaseModel, ConfigDict, Field

MAX_DURATION_MS = 3_600_000
STATS_YEAR_MIN = 2000
STATS_YEAR_MAX = 2100

SourceName = Literal["manual", "ai", "mcp", "copied"]
RatingName = Literal["again", "hard", "medium", "easy"]


class CardBody(BaseModel):
    """One card of POST /v1/me/flashcard-sets."""

    front: str = Field(min_length=CARD_TEXT_MIN, max_length=CARD_TEXT_MAX)
    back: str = Field(min_length=CARD_TEXT_MIN, max_length=CARD_TEXT_MAX)


class CardWithIdBody(CardBody):
    """One card of PUT /v1/me/flashcard-sets/{id}/cards; `id` keeps its progress."""

    id: UUID | None = None


class CreateSetBody(BaseModel):
    """POST /v1/me/flashcard-sets."""

    title: str = Field(min_length=TITLE_MIN, max_length=TITLE_MAX)
    description: str | None = Field(default=None, max_length=DESCRIPTION_MAX)
    cards: list[CardBody] = Field(max_length=MAX_CARDS_PER_SET)


class UpdateSetBody(BaseModel):
    """PATCH /v1/me/flashcard-sets/{id}; send only the fields to change."""

    title: str | None = Field(default=None, min_length=TITLE_MIN, max_length=TITLE_MAX)
    description: str | None = Field(default=None, max_length=DESCRIPTION_MAX)
    new_per_day: int | None = Field(
        default=None, ge=NEW_PER_DAY_MIN, le=NEW_PER_DAY_MAX
    )
    reviews_per_day: int | None = Field(
        default=None, ge=REVIEWS_PER_DAY_MIN, le=REVIEWS_PER_DAY_MAX
    )


class ReplaceCardsBody(BaseModel):
    """PUT /v1/me/flashcard-sets/{id}/cards: the full ordered list."""

    cards: list[CardWithIdBody] = Field(max_length=MAX_CARDS_PER_SET)


class ReviewBody(BaseModel):
    """POST /v1/me/flashcards/{card_id}/review.

    `duration_ms` is how long the student looked at the card (the server keeps at
    most one minute of it).
    """

    rating: RatingName
    duration_ms: int | None = Field(default=None, ge=0, le=MAX_DURATION_MS)


class CopyBody(BaseModel):
    """POST /v1/me/flashcard-sets/copy."""

    share_slug: str = Field(min_length=1, max_length=64)


class _Response(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class SetItemResponse(_Response):
    """FlashcardSetItem."""

    id: UUID
    title: str
    description: str | None
    source: SourceName
    card_count: int
    due_today: int
    new_today: int
    new_count: int
    learning_count: int
    due_count: int

    @classmethod
    def from_view(cls, view: SetItemView) -> Self:
        """Build from the use case view."""
        return cls.model_validate(view)


class CardResponse(_Response):
    """One card of FlashcardSetDetail."""

    id: UUID
    position: int
    front: str
    back: str
    state: str
    due_at: datetime | None


class SetDetailResponse(SetItemResponse):
    """FlashcardSetDetail = FlashcardSetItem plus limits and cards."""

    new_per_day: int
    reviews_per_day: int
    cards: list[CardResponse]

    @classmethod
    def from_detail(cls, view: SetDetailView) -> Self:
        """Build from the use case view."""
        return cls.model_validate(view)


class StudyCardResponse(_Response):
    """The card to show now."""

    id: UUID
    front: str
    back: str
    state: str


class IntervalsResponse(_Response):
    """Labels of the four buttons, e.g. "10m" or "4d"."""

    again: str
    hard: str
    medium: str
    easy: str


class CountsResponse(_Response):
    """Cards waiting in each queue."""

    learning: int
    review: int
    new: int


class StudyNextResponse(_Response):
    """StudyNext."""

    set_id: UUID
    card: StudyCardResponse | None
    intervals: IntervalsResponse | None
    counts: CountsResponse
    done_for_today: bool

    @classmethod
    def from_view(cls, view: StudyNextView) -> Self:
        """Build from the use case view."""
        return cls.model_validate(view)


class DayCountResponse(_Response):
    """Reviews on one study day (a Tashkent calendar day)."""

    date: date
    count: int


class ReviewStatsResponse(_Response):
    """ReviewStats: the heatmap and the numbers of Anki's deck overview."""

    year: int
    set_id: UUID | None
    days: list[DayCountResponse]
    total_reviews: int
    days_studied: int
    daily_average: float
    days_learned_percent: float
    longest_streak: int
    current_streak: int
    first_review_date: date | None
    today_count: int
    today_seconds: int

    @classmethod
    def from_view(cls, view: ReviewStatsView) -> Self:
        """Build from the use case view."""
        return cls.model_validate(view)
