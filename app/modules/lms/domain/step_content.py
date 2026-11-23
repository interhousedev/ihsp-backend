"""Step content: the JSON document of a course step (spec -> Course versioning)."""

import copy
import hashlib
import json
import secrets
from collections.abc import Iterator
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

ShowAnswers = Literal["never", "after_submit", "after_pass", "after_last_attempt"]
QuestionType = Literal[
    "single",
    "multiple",
    "text",
    "number",
    "sorting",
    "matching",
    "table",
    "blanks",
    "random_number",
    "formula",
    "free",
    "code",
]
FormulaMode = Literal["symbolic", "numeric"]
VideoSource = Literal["link", "upload"]
CaptionLang = Literal["uz", "ru", "en"]
InteractionKind = Literal["question", "note", "link"]
MAX_TABLE_SIDE = 30
MAX_VARIABLES = 10


class Card(BaseModel):
    """A flash card of a flash card block."""

    id: str = ""
    front: str
    back: str


class Option(BaseModel):
    """An answer option of a single or multiple choice question."""

    id: str = ""
    text: str
    correct: bool = False
    pinned: bool = False


class AnswerConfig(BaseModel):
    """Accepted answers of a text or number question."""

    accepted: list[str] | None = None
    regex: str | None = None
    case_sensitive: bool = False
    value: float | None = None
    tolerance: float = 0.0


class Pair(BaseModel):
    """A left item and its right match of a matching question."""

    id: str = ""
    left: str
    right: str


class TableSpec(BaseModel):
    """A grid of a table question: the cells to mark are ``correct[row][column]``."""

    rows: list[str] = Field(default_factory=list, max_length=MAX_TABLE_SIDE)
    columns: list[str] = Field(default_factory=list, max_length=MAX_TABLE_SIDE)
    correct: list[list[bool]] = Field(default_factory=list)

    @model_validator(mode="after")
    def _shape(self) -> "TableSpec":
        """``correct`` must have one row per row title and one cell per column."""
        if len(self.correct) != len(self.rows) or any(
            len(line) != len(self.columns) for line in self.correct
        ):
            raise ValueError("table.correct must match rows x columns")
        return self


class Blank(BaseModel):
    """One blank of a fill-in-the-blanks question.

    Marked ``{{n}}`` (1-based) in the prompt.
    """

    id: str = ""
    accepted: list[str] = Field(default_factory=list, max_length=50)
    regex: str | None = Field(default=None, max_length=200)
    case_sensitive: bool = False


class Variable(BaseModel):
    """A random variable of a generated numeric question."""

    name: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,15}$")
    min: float
    max: float
    integer: bool = True

    @model_validator(mode="after")
    def _range(self) -> "Variable":
        """The range must not be empty."""
        if self.min > self.max:
            raise ValueError("variable min must not exceed max")
        return self


class RandomSpec(BaseModel):
    """Variables and the formula of the answer; each attempt draws its own values."""

    variables: list[Variable] = Field(default_factory=list, max_length=MAX_VARIABLES)
    formula: str = Field(default="", max_length=500)
    tolerance: float = Field(default=0.01, ge=0)

    @model_validator(mode="after")
    def _unique(self) -> "RandomSpec":
        """Variable names are unique."""
        names = [variable.name for variable in self.variables]
        if len(set(names)) != len(names):
            raise ValueError("duplicate variable name")
        return self


class FormulaSpec(BaseModel):
    """The expected expression of a math formula question."""

    expression: str = Field(default="", max_length=500)
    variables: list[str] = Field(
        default_factory=lambda: ["x"], max_length=MAX_VARIABLES
    )
    mode: FormulaMode = "symbolic"
    tolerance: float = Field(default=1e-6, ge=0)


class CodeSpec(BaseModel):
    """A code question: no execution.

    The output is compared, or the answer is graded by hand.
    """

    language: str = Field(default="python", max_length=32)
    starter: str = Field(default="", max_length=10_000)
    expected_outputs: list[str] = Field(default_factory=list, max_length=20)


class Question(BaseModel):
    """A test question."""

    id: str = ""
    type: QuestionType
    prompt: str
    points: float = 1.0
    explanation: str | None = None
    options: list[Option] | None = None
    answer: AnswerConfig | None = None
    pairs: list[Pair] | None = Field(default=None, max_length=50)
    table: TableSpec | None = None
    blanks: list[Blank] | None = Field(default=None, max_length=50)
    random: RandomSpec | None = None
    formula: FormulaSpec | None = None
    code: CodeSpec | None = None


class TestConfig(BaseModel):
    """Test settings (LMS-16)."""

    __test__ = False  # not a pytest class, despite the name

    max_attempts: int | None = None
    passing_score_pct: float = 60.0
    shuffle_questions: bool = False
    shuffle_options: bool = False
    pool_size: int | None = None
    time_limit_sec: int | None = None
    cooldown_sec: int | None = None
    show_answers: ShowAnswers = "after_submit"


class TextBlock(BaseModel):
    """A markdown text block."""

    id: str = ""
    type: Literal["text"] = "text"
    markdown: str = ""


class TestBlock(BaseModel):
    """A test block with its settings and questions."""

    __test__ = False  # not a pytest class, despite the name

    id: str = ""
    type: Literal["test"] = "test"
    config: TestConfig = Field(default_factory=TestConfig)
    questions: list[Question] = Field(default_factory=list)


class CaptionTrack(BaseModel):
    """A WebVTT caption track of a video (WCAG 1.2.2), one per language."""

    lang: CaptionLang
    label: str = Field(min_length=1, max_length=60)
    file_id: str
    default: bool = False

    @model_validator(mode="after")
    def _valid_file(self) -> "CaptionTrack":
        """The track is an uploaded `lms_captions` file."""
        try:
            UUID(self.file_id)
        except ValueError as exc:
            raise ValueError("a caption track needs a valid file_id") from exc
        return self


class VideoBlock(BaseModel):
    """A video: a link (YouTube, Vimeo, direct file) or an uploaded file.

    ``captions`` are WebVTT tracks; players show them on native video only
    (embedded YouTube/Vimeo players use their own captions).
    """

    id: str = ""
    type: Literal["video"] = "video"
    source: VideoSource = "link"
    url: str = Field(default="", max_length=2000)
    file_id: str | None = None
    caption: str = Field(default="", max_length=500)
    captions: list[CaptionTrack] = Field(default_factory=list, max_length=3)

    @model_validator(mode="after")
    def _captions_are_consistent(self) -> "VideoBlock":
        """One track per language and at most one default track."""
        langs = [track.lang for track in self.captions]
        if len(set(langs)) != len(langs):
            raise ValueError("a video has at most one caption track per language")
        if sum(track.default for track in self.captions) > 1:
            raise ValueError("a video has at most one default caption track")
        return self

    @model_validator(mode="after")
    def _source_matches_fields(self) -> "VideoBlock":
        """An upload needs a file ID (and has no link); a link has no file."""
        if self.source == "upload":
            try:
                UUID(self.file_id or "")
            except ValueError as exc:
                raise ValueError("an uploaded video needs a valid file_id") from exc
            self.url = ""
        else:
            self.file_id = None
        return self


class FlashcardsBlock(BaseModel):
    """A block of flash cards studied with spaced repetition."""

    id: str = ""
    type: Literal["flashcards"] = "flashcards"
    cards: list[Card] = Field(default_factory=list)


class H5PBlock(BaseModel):
    """An uploaded H5P package, played in the browser with h5p-standalone."""

    id: str = ""
    type: Literal["h5p"] = "h5p"
    package_id: str = Field(default="", max_length=36)
    title: str = Field(default="", max_length=500)
    main_library: str = Field(default="", max_length=200)
    passing_score_pct: float = Field(default=0.0, ge=0, le=100)

    @model_validator(mode="after")
    def _package_id(self) -> "H5PBlock":
        """An empty package id is a block that has no package yet."""
        if self.package_id:
            try:
                UUID(self.package_id)
            except ValueError as exc:
                raise ValueError("h5p package_id must be a UUID") from exc
        return self


class Interaction(BaseModel):
    """A pause of an interactive video: a question, a note or a link."""

    id: str = ""
    at_sec: float = Field(ge=0, le=24 * 3600)
    kind: InteractionKind = "question"
    text: str = Field(default="", max_length=2000)
    options: list[Option] = Field(default_factory=list, max_length=10)
    multiple: bool = False
    url: str = Field(default="", max_length=2000)
    points: float = Field(default=1.0, ge=0, le=100)

    @model_validator(mode="after")
    def _kind_fields(self) -> "Interaction":
        """Only questions keep options; a link URL must be http(s) when set."""
        if self.url and not self.url.startswith(("https://", "http://")):
            raise ValueError("an interactive video link needs an http(s) URL")
        if self.kind != "question":
            self.options = []
        return self


class InteractiveVideoBlock(BaseModel):
    """A video that pauses at timestamps for questions, notes and links."""

    id: str = ""
    type: Literal["interactive_video"] = "interactive_video"
    source: VideoSource = "link"
    url: str = Field(default="", max_length=2000)
    file_id: str | None = None
    caption: str = Field(default="", max_length=500)
    interactions: list[Interaction] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def _source_and_order(self) -> "InteractiveVideoBlock":
        """Same source rules as a video.

        Interactions keep the author's order (the editor matches server ids by
        position); the player sorts them by ``at_sec``.
        """
        if self.source == "upload":
            try:
                UUID(self.file_id or "")
            except ValueError as exc:
                raise ValueError("an uploaded video needs a valid file_id") from exc
            self.url = ""
        else:
            self.file_id = None
        return self


ExamKind = Literal["sat", "ap", "custom"]
Calculator = Literal["none", "scientific", "graphing"]
EXAM_QUESTION_TYPES = frozenset({"single", "multiple", "number", "text", "free"})


class ExamModule(BaseModel):
    """A timed module of an exam section (Bluebook: section 1, module 2)."""

    id: str = ""
    title: str = Field(default="", max_length=200)
    time_limit_sec: int = Field(default=1920, ge=60, le=14_400)
    questions: list[Question] = Field(default_factory=list, max_length=200)

    @model_validator(mode="after")
    def _question_types(self) -> "ExamModule":
        """An exam asks only choice, number, text and free answer questions."""
        for question in self.questions:
            if question.type not in EXAM_QUESTION_TYPES:
                raise ValueError(f"exam question type not allowed: {question.type}")
        return self


class ExamSection(BaseModel):
    """A section of an exam: modules taken in order, optionally adaptive."""

    id: str = ""
    title: str = Field(default="", max_length=200)
    modules: list[ExamModule] = Field(default_factory=list, max_length=4)
    adaptive: bool = False


class ExamScaling(BaseModel):
    """The scaled score range of every section (SAT: 200 to 800)."""

    min_score: int = Field(default=200, ge=0, le=10_000)
    max_score: int = Field(default=800, ge=1, le=10_000)

    @model_validator(mode="after")
    def _range(self) -> "ExamScaling":
        """The maximum is above the minimum."""
        if self.max_score <= self.min_score:
            raise ValueError("max_score must be greater than min_score")
        return self


class ExamBlock(BaseModel):
    """A Bluebook-style digital test (SAT, AP or custom) with timed modules."""

    id: str = ""
    type: Literal["exam"] = "exam"
    title: str = Field(default="", max_length=200)
    kind: ExamKind = "custom"
    directions: str = Field(default="", max_length=5000)
    reference_sheet: str = Field(default="", max_length=20_000)
    calculator: Calculator = "none"
    sections: list[ExamSection] = Field(default_factory=list, max_length=6)
    scaling: ExamScaling | None = None


CodeLanguage = Literal["python", "javascript", "sql"]


class CodeTest(BaseModel):
    """A test of a code block; hidden tests show only their name to students."""

    id: str = ""
    name: str = Field(default="", max_length=200)
    code: str = Field(default="", max_length=5000)
    hidden: bool = False


class CodeBlock(BaseModel):
    """A runnable code panel with starter code, an author solution and tests."""

    id: str = ""
    type: Literal["code"] = "code"
    language: CodeLanguage = "python"
    instructions: str = Field(default="", max_length=5000)
    starter: str = Field(default="", max_length=20_000)
    solution: str = Field(default="", max_length=20_000)
    tests: list[CodeTest] = Field(default_factory=list, max_length=30)
    time_limit_ms: int = Field(default=5000, ge=1000, le=30_000)
    graded: bool = False


class HtmlBlock(BaseModel):
    """An author-uploaded custom HTML widget, served sandboxed."""

    id: str = ""
    type: Literal["html"] = "html"
    title: str = Field(default="", max_length=200)
    package_id: str = Field(default="", max_length=36)
    entry: Literal["index.html"] = "index.html"
    height_px: int = Field(default=600, ge=200, le=2000)
    allow_fullscreen: bool = False
    graded: bool = False

    @model_validator(mode="after")
    def _package_id(self) -> "HtmlBlock":
        """An empty package id is a block that has no upload yet."""
        if self.package_id:
            try:
                UUID(self.package_id)
            except ValueError as exc:
                raise ValueError("html package_id must be a UUID") from exc
        return self


AiReviewTemplate = Literal[
    "review_table", "rubric_checklist", "strengths_cards", "image_gallery"
]
AiReviewFileKind = Literal["pdf", "docx", "pptx", "image", "text"]


class AiReviewCriterion(BaseModel):
    """One row of the review: a criterion, what it means and its top score."""

    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=1000)
    max_score: float = Field(default=10, ge=0, le=100)


class AiReviewFile(BaseModel):
    """A reference file the teacher uploaded; its text is never shown to students."""

    file_id: str = Field(max_length=36)
    name: str = Field(default="", max_length=200)

    @model_validator(mode="after")
    def _file_id(self) -> "AiReviewFile":
        """The file id is a UUID of the files module."""
        try:
            UUID(self.file_id)
        except ValueError as exc:
            raise ValueError("ai_review file_id must be a UUID") from exc
        return self


class AiReviewBlock(BaseModel):
    """An AI reviewer of a student's work (intermediate project review).

    Only ``title``, ``instructions_public``, ``max_submissions``, ``accepted_types``
    and the template name reach students; the prompt, files, private topics and
    criteria descriptions stay on the server.
    """

    id: str = ""
    type: Literal["ai_review"] = "ai_review"
    title: str = Field(default="", max_length=200)
    instructions_public: str = Field(default="", max_length=10_000)
    teacher_prompt: str = Field(default="", max_length=10_000)
    output_template: AiReviewTemplate = "review_table"
    criteria: list[AiReviewCriterion] = Field(default_factory=list, max_length=20)
    use_course_materials: bool = True
    reference_files: list[AiReviewFile] = Field(default_factory=list, max_length=10)
    web_search: bool = False
    private_topics: list[Annotated[str, Field(max_length=200)]] = Field(
        default_factory=list, max_length=30
    )
    max_submissions: int = Field(default=3, ge=1, le=20)
    pass_threshold_pct: int = Field(default=60, ge=0, le=100)
    """The share of the criteria's top scores a review needs to pass the block."""
    accepted_types: list[AiReviewFileKind] = Field(
        default_factory=lambda: list[AiReviewFileKind](
            ["pdf", "docx", "image", "text"]
        ),
        min_length=1,
    )


Block = Annotated[
    TextBlock
    | VideoBlock
    | TestBlock
    | FlashcardsBlock
    | H5PBlock
    | InteractiveVideoBlock
    | ExamBlock
    | CodeBlock
    | HtmlBlock
    | AiReviewBlock,
    Field(discriminator="type"),
]


Identified = (
    TextBlock
    | VideoBlock
    | TestBlock
    | FlashcardsBlock
    | H5PBlock
    | InteractiveVideoBlock
    | ExamBlock
    | CodeBlock
    | HtmlBlock
    | AiReviewBlock
    | ExamSection
    | ExamModule
    | CodeTest
    | Interaction
    | Question
    | Option
    | Card
    | Pair
    | Blank
)


class StepContent(BaseModel):
    """Title and blocks of a step (``CourseStep.draft``, ``StepRevision.content``)."""

    title: str
    blocks: list[Block] = Field(default_factory=list)


def canonical_hash(content: StepContent) -> str:
    """Return the SHA-256 of the canonical JSON (sorted keys) of the content."""
    data = content.model_dump(mode="json")
    canonical = json.dumps(
        data, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def _question_items(questions: list[Question]) -> Iterator[Identified]:
    """Yield questions with their options, pairs and blanks."""
    for question in questions:
        yield question
        yield from question.options or []
        yield from question.pairs or []
        yield from question.blanks or []


def _exam_items(block: ExamBlock) -> Iterator[Identified]:
    """Yield the sections, modules and questions of an exam."""
    for section in block.sections:
        yield section
        for module in section.modules:
            yield module
            yield from _question_items(module.questions)


def _items(content: StepContent) -> Iterator[Identified]:
    """Yield every element that carries an id: blocks, questions, options, cards."""
    for block in content.blocks:
        yield block
        if isinstance(block, TestBlock):
            yield from _question_items(block.questions)
        elif isinstance(block, ExamBlock):
            yield from _exam_items(block)
        elif isinstance(block, CodeBlock):
            yield from block.tests
        elif isinstance(block, FlashcardsBlock):
            yield from block.cards
        elif isinstance(block, InteractiveVideoBlock):
            for interaction in block.interactions:
                yield interaction
                yield from interaction.options


def assign_ids(content: StepContent, existing_ids: set[str]) -> StepContent:
    """Return a copy where every element has a server-assigned, unique id.

    Elements with an id in ``existing_ids`` keep it. Elements without an id (the
    empty string counts as none: MCP clients send ``""`` for new items), or with
    an id the server never issued, get a fresh 8-character random id.

    Raises:
        ValueError: The same id is used twice inside the content.
    """
    result = copy.deepcopy(content)
    seen: set[str] = set()
    for item in _items(result):
        if not item.id:
            continue
        if item.id in seen:
            raise ValueError(f"duplicate id in step content: {item.id}")
        seen.add(item.id)
    taken = set(existing_ids) | seen
    for item in _items(result):
        if not item.id or item.id not in existing_ids:
            item.id = _new_id(taken)
    return result


def _new_id(taken: set[str]) -> str:
    """Return a random 8-character id that is not in ``taken`` and remember it."""
    while True:
        candidate = secrets.token_urlsafe(6)
        if candidate not in taken:
            taken.add(candidate)
            return candidate
