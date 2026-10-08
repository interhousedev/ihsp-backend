"""Read models returned by learning use cases (JSON shapes of the API contract)."""

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

# - - - People and courses - - -


class LearningPersonRefView(BaseModel):
    """`PersonRef`: a person in lists."""

    id: UUID
    first_name: str
    last_name: str


class LearningCourseCardView(BaseModel):
    """`CourseCard`: a course in the catalog and in My courses."""

    id: UUID
    slug: str
    title: str
    description: str
    cover_url: str | None
    steps_count: int
    progress_pct: int | None
    visibility: Literal["public", "invite"]
    updated_at: datetime | None


class LearningCourseStaffItemView(BaseModel):
    """`CourseStaffItem`: a staff member shown on the course page."""

    user: LearningPersonRefView
    role: str
    permissions: list[str]
    show_on_page: bool
    position: int


class LearningOutlineStepView(BaseModel):
    """One step in an outline section."""

    step_id: UUID
    title: str
    completed: bool | None = None
    badge: Literal["new", "changed"] | None = None


class LearningOutlineSectionView(BaseModel):
    """`OutlineSection`: a section with its steps."""

    id: str
    title: str
    steps: list[LearningOutlineStepView]


class LearningCoursePageView(LearningCourseCardView):
    """`CoursePage`: the course card with staff, outline and my state."""

    staff: list[LearningCourseStaffItemView]
    outline: list[LearningOutlineSectionView]
    enrolled: bool
    can_edit: bool
    changed_since_last_visit: list[UUID]


class LearningMyCoursesView(BaseModel):
    """`GET /v1/lms/my-courses`: enrolled and managed courses."""

    enrolled: list[LearningCourseCardView]
    managed: list[LearningCourseCardView]


# - - - Attempts - - -


class LearningReviewItemView(BaseModel):
    """Correctness of one question, shown as `show_answers` allows."""

    question_id: str
    correct: bool
    correct_answer: dict[str, Any] | None = None
    explanation: str | None = None


class LearningAttemptResultView(BaseModel):
    """`AttemptResult`: the graded attempt."""

    id: UUID
    score: float
    max_score: float
    passed: bool
    submitted_at: datetime
    review: list[LearningReviewItemView] | None


class LearningAttemptReviewView(LearningAttemptResultView):
    """`AttemptReview`: an attempt for its owner or a reviewer."""

    user: LearningPersonRefView
    variant: dict[str, Any]
    answers: dict[str, dict[str, Any]]
    revision_id: UUID
    override_score: float | None
    override_comment: str | None


class LearningAttemptQuestionView(BaseModel):
    """A question of an attempt, without any correctness data."""

    id: str
    type: str
    prompt: str
    points: float
    options: list[dict[str, str]] | None = None


class LearningAttemptView(BaseModel):
    """`LearningAttemptView`: an attempt in progress."""

    id: UUID
    block_id: str
    attempt_no: int
    started_at: datetime
    deadline_at: datetime | None
    questions: list[LearningAttemptQuestionView]
    answers: dict[str, dict[str, Any]]
    submitted_at: datetime | None


# - - - Steps - - -


class LearningTextBlockView(BaseModel):
    """A text block of a step."""

    id: str
    type: Literal["text"]
    markdown: str


class LearningQuizRulesView(BaseModel):
    """What a student sees before starting a test."""

    questions: int
    attempts_left: int | None
    time_limit_sec: int | None
    passing_score_pct: float


class LearningQuizBlockView(BaseModel):
    """A test block of a step with my best result and open attempt."""

    id: str
    type: Literal["test"]
    rules: LearningQuizRulesView
    best: LearningAttemptResultView | None
    open_attempt_id: UUID | None


class LearningFlashcardsBlockView(BaseModel):
    """A flash card block of a step."""

    id: str
    type: Literal["flashcards"]
    cards_count: int
    due: int


StepBlockView = Annotated[
    LearningTextBlockView | LearningQuizBlockView | LearningFlashcardsBlockView,
    Field(discriminator="type"),
]


class LearningStepView(BaseModel):
    """`StepView`: a step as a student sees it, without any correct answers."""

    step_id: UUID
    revision_id: UUID
    title: str
    blocks: list[StepBlockView]
    completed: bool
    preview: bool


class LearningStepProgressView(BaseModel):
    """`StepProgressItem`: result of opening a step."""

    step_id: UUID
    viewed_at: datetime | None
    completed: bool


# - - - Flash cards - - -


class LearningCardView(BaseModel):
    """A flash card shown to a student."""

    id: str
    front: str
    back: str


class LearningCardIntervalsView(BaseModel):
    """When the card would come back after each button."""

    again: str
    hard: str
    medium: str
    easy: str


class LearningCardCountsView(BaseModel):
    """Cards left to study today."""

    learning: int
    review: int
    new: int


class LearningCardStudyView(BaseModel):
    """`LmsCardStudy`: the next card of a flash card block."""

    block_id: str
    card: LearningCardView | None
    intervals: LearningCardIntervalsView | None
    counts: LearningCardCountsView


# - - - Review - - -


class LearningStudentAttemptView(BaseModel):
    """An attempt in the list of a student."""

    id: UUID
    step_id: UUID
    block_id: str
    score: float
    max_score: float
    passed: bool
    submitted_at: datetime


class LearningCourseStudentView(BaseModel):
    """`CourseStudent`: an enrolled student with progress and attempts."""

    user: LearningPersonRefView
    progress_pct: int
    completed_at: datetime | None
    attempts: list[LearningStudentAttemptView]
