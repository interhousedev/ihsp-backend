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
    summary: str = ""
    accent_color: str | None = None
    cover_file_id: UUID | None = None
    # Audience rules: `locked` items are listed but cannot be opened; `access`
    # is "public", "signed_in", "students" or "chosen".
    locked: bool = False
    access: Literal["public", "signed_in", "students", "chosen"] = "public"


class LearningContactView(BaseModel):
    """Whom to ask for access to a locked item with a chosen audience."""

    name: str
    telegram: str | None = None


class LearningGuestStaffItemView(BaseModel):
    """A staff member as guests see them: the display name and order only."""

    name: str
    position: int


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
    # Points a perfect pass of the step's tests gives, and what the student has
    # earned (None when not enrolled).
    points_total: float = 0.0
    points_earned: float | None = None
    locked: bool = False
    # Why the step is locked: the audience rule or the mastery threshold.
    lock_reason: Literal["access", "mastery"] | None = None
    access: Literal["public", "signed_in", "students", "chosen"] = "public"
    # The type of the step's first block and the minutes it takes to work through.
    kind: str | None = None
    estimated_minutes: int | None = None


class LearningOutlineSectionView(BaseModel):
    """`OutlineSection`: a section with its steps."""

    id: str
    title: str
    steps: list[LearningOutlineStepView]


class LearningCoursePageBaseView(LearningCourseCardView):
    """The fields of the course page shared by learners and guests."""

    outline: list[LearningOutlineSectionView]
    enrolled: bool
    can_edit: bool
    changed_since_last_visit: list[UUID]
    # Course totals for the learner sidebar and the promo page; the "earned"
    # values are None when the viewer is not enrolled.
    steps_completed: int | None = None
    points_total: float = 0.0
    points_earned: float | None = None
    # Set when the course or a lesson is locked for a chosen audience.
    contact: LearningContactView | None = None
    # How the viewer joined and where to resume (None when not enrolled).
    enrolled_via: str | None = None
    continue_step_id: UUID | None = None


class LearningCoursePageView(LearningCoursePageBaseView):
    """`CoursePage`: the course card with staff, outline and my state."""

    staff: list[LearningCourseStaffItemView]


class LearningGuestCoursePageView(LearningCoursePageBaseView):
    """The course page for guests: no ids or permissions of the staff."""

    staff: list[LearningGuestStaffItemView]


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
    lefts: list[dict[str, str]] | None = None
    rights: list[dict[str, str]] | None = None
    table: dict[str, list[str]] | None = None
    blanks: int | None = None
    variables: list[str] | None = None
    code: dict[str, Any] | None = None


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
    passed: bool = False


class LearningCaptionTrackView(BaseModel):
    """A WebVTT caption track of a video block (its file comes from `/captions`)."""

    lang: Literal["uz", "ru", "en"]
    label: str
    default: bool = False


class LearningVideoBlockView(BaseModel):
    """A video block of a step."""

    id: str
    type: Literal["video"]
    source: Literal["link", "upload"]
    url: str
    file_id: str | None = None
    caption: str = ""
    captions: list[LearningCaptionTrackView] = Field(default_factory=list)
    passed: bool = False


class VideoStreamView(BaseModel):
    """A short-lived URL that streams an uploaded video (supports ``Range``)."""

    url: str
    expires_in: int


class CaptionUrlView(BaseModel):
    """A short-lived URL of one WebVTT caption track."""

    lang: Literal["uz", "ru", "en"]
    label: str
    default: bool
    url: str


class VideoCaptionsView(BaseModel):
    """The caption tracks of a video block with short-lived URLs."""

    tracks: list[CaptionUrlView]
    expires_in: int


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
    passed: bool = False
    points_total: float = 0.0
    points_earned: float = 0.0


class LearningFlashcardsBlockView(BaseModel):
    """A flash card block of a step."""

    id: str
    type: Literal["flashcards"]
    cards_count: int
    due: int
    passed: bool = False


class LearningBlockResultView(BaseModel):
    """My result of an H5P, interactive video, code or HTML block (best score).

    ``verified`` is false for code and HTML widgets: the browser graded them, so
    the score is self-reported and earns no points.
    """

    score: float = 0.0
    max_score: float = 0.0
    completed: bool = False
    verified: bool = True


class LearningH5PBlockView(BaseModel):
    """An H5P block; ``GET .../h5p`` returns the signed base URL of the package."""

    id: str
    type: Literal["h5p"]
    package_id: str
    title: str = ""
    main_library: str = ""
    passing_score_pct: float = 0.0
    result: LearningBlockResultView | None = None
    passed: bool = False


class LearningInteractionOptionView(BaseModel):
    """An answer option of an interactive video question (no correctness)."""

    id: str
    text: str


class LearningInteractionView(BaseModel):
    """A pause of an interactive video."""

    id: str
    at_sec: float
    kind: Literal["question", "note", "link"]
    text: str = ""
    url: str = ""
    multiple: bool = False
    points: float = 1.0
    options: list[LearningInteractionOptionView] = Field(default_factory=list)


class LearningInteractionAnswerView(BaseModel):
    """My first answer to an interactive video question."""

    option_ids: list[str]
    correct: bool


class LearningInteractionResultView(BaseModel):
    """The graded answer, the right options (shown after answering) and the total."""

    answer: LearningInteractionAnswerView
    correct_option_ids: list[str]
    result: LearningBlockResultView


class LearningInteractiveVideoBlockView(BaseModel):
    """An interactive video block with my answers so far."""

    id: str
    type: Literal["interactive_video"]
    source: Literal["link", "upload"]
    url: str
    file_id: str | None = None
    caption: str = ""
    interactions: list[LearningInteractionView] = Field(default_factory=list)
    answers: dict[str, LearningInteractionAnswerView] = Field(default_factory=dict)
    result: LearningBlockResultView | None = None
    passed: bool = False


class H5PLaunchView(BaseModel):
    """Where the player loads an H5P package from (signed, short-lived)."""

    base_url: str
    expires_in: int


class HtmlWidgetLaunchView(BaseModel):
    """Where the frame loads an HTML widget from (signed, short-lived)."""

    base_url: str
    entry_url: str
    expires_in: int


class LearningExamModuleView(BaseModel):
    """A timed module of an exam section, without its questions."""

    id: str
    title: str = ""
    time_limit_sec: int
    questions_count: int


class LearningExamSectionView(BaseModel):
    """A section of an exam."""

    id: str
    title: str = ""
    adaptive: bool = False
    modules: list[LearningExamModuleView] = Field(default_factory=list)


class LearningExamScalingView(BaseModel):
    """The scaled score range of every section."""

    min_score: int
    max_score: int


class LearningExamBlockView(BaseModel):
    """An exam block: structure, directions and timing; no questions or answers."""

    id: str
    type: Literal["exam"]
    title: str = ""
    kind: Literal["sat", "ap", "custom"]
    directions: str = ""
    reference_sheet: str = ""
    calculator: Literal["none", "scientific", "graphing"]
    sections: list[LearningExamSectionView] = Field(default_factory=list)
    scaling: LearningExamScalingView | None = None
    passed: bool = False
    result: LearningBlockResultView | None = None


ExamStatus = Literal["not_started", "in_module", "between", "finished"]


class LearningExamModuleRefView(BaseModel):
    """Where a module sits in an exam (1-based numbers, as Bluebook shows them)."""

    section_id: str
    module_id: str
    section_title: str = ""
    module_title: str = ""
    section_no: int
    module_no: int
    time_limit_sec: int
    questions_count: int


class LearningExamModuleRunView(LearningExamModuleRefView):
    """The open module: its questions (no answers) and the server-side timer."""

    started_at: datetime
    deadline_at: datetime
    questions: list["LearningAttemptQuestionView"]
    answers: dict[str, dict[str, Any]]


class LearningExamSectionScoreView(BaseModel):
    """The raw and scaled score of one section."""

    section_id: str
    title: str = ""
    score: float
    max_score: float
    scaled_score: int | None = None


class LearningExamModuleReviewView(LearningExamModuleRefView):
    """A finished module with my answers, correct answers and explanations."""

    late: bool = False
    score: float
    max_score: float
    questions: list["LearningAttemptQuestionView"]
    answers: dict[str, dict[str, Any]]
    review: list[LearningReviewItemView]


class LearningExamResultView(BaseModel):
    """The graded exam: section scores, total and the review of every module."""

    finished_at: datetime
    score: float
    max_score: float
    scaled_total: int | None = None
    scaled_min: int | None = None
    scaled_max: int | None = None
    sections: list[LearningExamSectionScoreView]
    modules: list[LearningExamModuleReviewView]


class LearningExamSessionView(BaseModel):
    """My sitting of an exam block; questions only of the module that is open."""

    block_id: str
    status: ExamStatus
    server_now: datetime
    modules_done: int
    current: LearningExamModuleRunView | None = None
    next: LearningExamModuleRefView | None = None
    next_is_new_section: bool = False
    result: LearningExamResultView | None = None


class LearningCodeTestView(BaseModel):
    """A code block test; a hidden test keeps its name and has empty code."""

    id: str
    name: str = ""
    hidden: bool = False
    code: str = ""


class LearningHiddenTestsView(BaseModel):
    """The hidden tests of a graded code block, fetched when the student submits."""

    tests: list[LearningCodeTestView] = Field(default_factory=list)


class LearningCodeBlockView(BaseModel):
    """A runnable code panel, without the author's solution."""

    id: str
    type: Literal["code"]
    language: Literal["python", "javascript", "sql"]
    instructions: str = ""
    starter: str = ""
    tests: list[LearningCodeTestView] = Field(default_factory=list)
    time_limit_ms: int
    graded: bool = False
    passed: bool = False
    result: LearningBlockResultView | None = None


class LearningHtmlBlockView(BaseModel):
    """An author-uploaded HTML widget."""

    id: str
    type: Literal["html"]
    title: str = ""
    package_id: str = ""
    entry: str = "index.html"
    height_px: int
    allow_fullscreen: bool = False
    graded: bool = False
    passed: bool = False
    result: LearningBlockResultView | None = None


class LearningAiReviewCriterionView(BaseModel):
    """A public criterion of an AI review: its name and top score."""

    name: str
    max_score: float


class LearningAiReviewBlockView(BaseModel):
    """An AI review of my work; the teacher's prompt and files are not included."""

    id: str
    type: Literal["ai_review"]
    title: str = ""
    instructions_public: str = ""
    output_template: Literal[
        "review_table", "rubric_checklist", "strengths_cards", "image_gallery"
    ]
    criteria: list[LearningAiReviewCriterionView] = Field(default_factory=list)
    max_submissions: int
    accepted_types: list[Literal["pdf", "docx", "pptx", "image", "text"]] = Field(
        default_factory=list
    )
    passed: bool | None = None


StepBlockView = Annotated[
    LearningTextBlockView
    | LearningVideoBlockView
    | LearningQuizBlockView
    | LearningFlashcardsBlockView
    | LearningH5PBlockView
    | LearningInteractiveVideoBlockView
    | LearningExamBlockView
    | LearningCodeBlockView
    | LearningHtmlBlockView
    | LearningAiReviewBlockView,
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
    # Block counts and points for the lesson header and the step strip.
    blocks_total: int = 0
    blocks_passed: int = 0
    points_total: float = 0.0
    points_earned: float = 0.0


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


class LearningStudentWidgetResultView(BaseModel):
    """A graded code or HTML widget result of a student (browser-graded)."""

    step_id: UUID
    block_id: str
    score_pct: float
    passed: bool
    verified: bool


class LearningCourseStudentView(BaseModel):
    """`CourseStudent`: an enrolled student with progress and attempts."""

    user: LearningPersonRefView
    progress_pct: int
    completed_at: datetime | None
    attempts: list[LearningStudentAttemptView]
    widget_results: list[LearningStudentWidgetResultView] = []


# - - - Landing page - - -


class LearningLandingEnrolmentView(BaseModel):
    """Enrolment window and whether the viewer can join now."""

    open: bool
    starts_at: datetime | None
    ends_at: datetime | None
    can_enrol: bool
    enrolled: bool


class LearningLandingStepView(BaseModel):
    """A lesson in the syllabus."""

    title: str


class LearningLandingSectionView(BaseModel):
    """A syllabus section with its lesson titles."""

    title: str
    steps: list[LearningLandingStepView]


class LearningLandingAuthorView(BaseModel):
    """A staff member shown on the landing page."""

    user: LearningPersonRefView
    role: str


class LearningLandingView(BaseModel):
    """`CourseLanding`: the public page of a course."""

    id: UUID
    slug: str
    title: str
    friendly_name: str | None
    summary: str
    description: str
    cover_file_id: UUID | None
    cover_url: str | None
    banner_file_id: UUID | None
    banner_url: str | None
    accent_color: str | None
    language: str
    level: str | None
    workload_hours_per_week: int | None
    duration_weeks: int | None
    tags: list[str]
    outcomes: list[str]
    requirements: list[str]
    audience: list[str]
    publish_state: str
    preview: bool
    authors: list[LearningLandingAuthorView]
    syllabus: list[LearningLandingSectionView]
    enrolment: LearningLandingEnrolmentView
