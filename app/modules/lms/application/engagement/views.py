"""Read models of the engagement API (frozen contract, Asia/Tashkent dates)."""

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from app.modules.lms.domain.engagement.streak import DayState
from app.modules.lms.domain.engagement.xp import XpSource

from pydantic import BaseModel, Field

GoalKind = Literal["steps", "xp", "review_days"]


class EngagementWeekDayView(BaseModel):
    """One day of the current Mon-Sun week."""

    date: date
    state: DayState


class EngagementStreakView(BaseModel):
    """School-week streak."""

    current: int
    best: int
    freezes: int
    today_done: bool
    week: list[EngagementWeekDayView]


class EngagementSummaryView(BaseModel):
    """XP, level, streak, due reviews and the weekly goal."""

    xp_total: int
    level: int
    xp_into_level: int
    xp_for_next: int
    streak: EngagementStreakView
    review_due: int
    weekly_goal_days: int


class EngagementXpItemView(BaseModel):
    """One XP award."""

    source: XpSource
    ref: str
    xp: int
    at: datetime


class EngagementXpListView(BaseModel):
    """Newest XP awards."""

    items: list[EngagementXpItemView]


class EngagementCardView(BaseModel):
    """A flashcard to recall."""

    front: str
    back: str


class EngagementReviewItemView(BaseModel):
    """One item of the daily review."""

    item_id: str
    kind: Literal["question", "flashcard"]
    course_id: UUID
    step_id: UUID
    question: dict[str, Any] | None
    card: EngagementCardView | None


class EngagementReviewQueueView(BaseModel):
    """Today's review queue (at most 20 answers a day)."""

    items: list[EngagementReviewItemView]


class EngagementAnswerResultView(BaseModel):
    """Feedback on a review answer."""

    correct: bool
    correct_answer: dict[str, Any] | None
    explanation: str | None
    next_due: datetime
    xp: int


class EngagementGradeResultView(BaseModel):
    """Result of a flashcard rating."""

    next_due: datetime
    xp: int


class EngagementMasteryStepView(BaseModel):
    """A step in the mastery map."""

    step_id: UUID
    title: str
    best_pct: int | None
    completed: bool


class EngagementMasterySectionView(BaseModel):
    """A section with its mastery."""

    section_id: str
    title: str
    mastery_pct: int | None
    unlocked: bool
    steps: list[EngagementMasteryStepView]


class EngagementMasteryView(BaseModel):
    """The mastery map of a course."""

    unlock_threshold_pct: int | None
    sections: list[EngagementMasterySectionView]


class EngagementQuestView(BaseModel):
    """A class quest with the learner's and the class's progress (no ranking)."""

    id: UUID
    course_id: UUID
    course_title: str
    title: str
    goal_kind: GoalKind
    target: int
    my_progress: int
    class_progress: int
    class_target: int
    starts_on: date
    ends_on: date
    done: bool


class EngagementQuestListView(BaseModel):
    """Quests."""

    items: list[EngagementQuestView]


class EngagementSettingsView(BaseModel):
    """Course engagement settings."""

    unlock_threshold_pct: int | None = Field(default=None, ge=1, le=100)


class EngagementQuestInput(BaseModel):
    """A quest as staff edit it."""

    title: str = Field(min_length=1, max_length=200)
    goal_kind: GoalKind
    target: int = Field(ge=1, le=100000)
    class_target: int = Field(ge=1, le=10000)
    starts_on: date
    ends_on: date
