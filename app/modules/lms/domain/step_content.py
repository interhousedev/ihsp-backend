"""Step content: the JSON document of a course step (README -> Course versioning)."""

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
    """One blank of a fill-in-the-blanks question, marked ``{{n}}`` (1-based) in the prompt."""

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
    """A code question: no execution; the output is compared or the answer is graded by hand."""

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


class VideoBlock(BaseModel):
    """A video: a link (YouTube, Vimeo, direct file) or an uploaded file."""

    id: str = ""
    type: Literal["video"] = "video"
    source: VideoSource = "link"
    url: str = Field(default="", max_length=2000)
    file_id: str | None = None
    caption: str = Field(default="", max_length=500)

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


Block = Annotated[
    TextBlock | VideoBlock | TestBlock | FlashcardsBlock, Field(discriminator="type")
]


Identified = (
    TextBlock
    | VideoBlock
    | TestBlock
    | FlashcardsBlock
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


def _items(content: StepContent) -> Iterator[Identified]:
    """Yield every element that carries an id: blocks, questions, options, cards."""
    for block in content.blocks:
        yield block
        if isinstance(block, TestBlock):
            for question in block.questions:
                yield question
                yield from question.options or []
                yield from question.pairs or []
                yield from question.blanks or []
        elif isinstance(block, FlashcardsBlock):
            yield from block.cards


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
