"""Input models and builders of LMS step blocks, shared by the MCP server and the AI.

The LMS Course MCP server and the course author assistant add the same kinds of blocks
(Markdown text, tests, flash cards) to a draft step. The argument models below are
what both show to a model as a JSON schema, and the builders turn them into blocks in
the shape of the LMS ``Block`` contract. Ids are left empty: the server assigns random
ids to blocks, questions, options and cards (LMS-23).
"""

from collections.abc import Callable
from typing import Annotated, Any, ClassVar, Final, Literal, get_args
from uuid import UUID

from pydantic import BaseModel, Field


class BlockInputError(ValueError):
    """The arguments are well formed but break a rule; the text says which one."""


# - - - Argument models - - -


PLAIN_KEY: Final = "x-plain"
_plain: Final[dict[str, Any]] = {PLAIN_KEY: True}
"""Marks an optional field that a tool schema shows without ``null``.

Providers compile a strict tool schema only while at most 16 properties are
nullable; the question model alone has more optional fields than that. In the tool
schema (``strict_tool_parameters``) the model writes ``[]`` or ``""`` for "not used"
and the builders treat both as absent, while Python callers may still pass ``None``
and the HTTP API keeps the nullable schema.
"""

CardText = Annotated[str, Field(min_length=1, max_length=2000)]


class FlashcardInput(BaseModel):
    """One flash card to create."""

    front: CardText = Field(description="Question side of the card.")
    back: CardText = Field(description="Answer side of the card.")


CardList = Annotated[
    list[FlashcardInput],
    Field(min_length=1, max_length=200, description="Cards to add (at most 200)."),
]


def card_pairs(cards: list[FlashcardInput]) -> list[tuple[str, str]]:
    """Convert card inputs to the (front, back) pairs FlashcardsApi takes."""
    return [(card.front, card.back) for card in cards]


class OptionInput(BaseModel):
    """One answer option of a single or multiple choice question."""

    text: str = Field(min_length=1, max_length=500, description="Option text.")
    correct: bool = Field(default=False, description="True for a correct option.")
    pinned: bool = Field(
        default=False,
        description=(
            "Keep this option in place when options are shuffled, "
            'e.g. "None of the above".'
        ),
    )


class PairInput(BaseModel):
    """A matching pair: a left item and the right item that belongs to it."""

    left: str = Field(min_length=1, max_length=500)
    right: str = Field(min_length=1, max_length=500)


class BlankInput(BaseModel):
    """One blank of a fill-in-the-blanks question (``{{1}}``, ``{{2}}`` in the prompt)."""  # noqa: E501

    accepted: list[str] = Field(default_factory=list, max_length=20)
    regex: str | None = Field(default=None, max_length=200, json_schema_extra=_plain)


class VariableInput(BaseModel):
    """A random variable of a generated numeric question."""

    name: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,15}$")
    min: float
    max: float
    integer: bool = True


class QuestionInput(BaseModel):
    """A test question. Fill the fields that belong to its type."""

    type: Literal[
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
    ] = Field(
        description=(
            "single: one correct option; multiple: several; text; number; "
            "sorting: `items` in the right order; matching: `pairs`; "
            "table: `rows`, `columns`, `correct_cells`; blanks: `blanks`; "
            "random_number: `variables` and `formula`; formula: `expression`; "
            "code: optional `expected_outputs`; free: graded by a teacher."
        )
    )
    prompt: str = Field(min_length=1, max_length=2000, description="Question text.")
    points: int = Field(
        default=1, ge=1, le=100, description="Score for a right answer."
    )
    explanation: str | None = Field(
        default=None,
        max_length=2000,
        description="Shown after answering, if allowed.",
        json_schema_extra=_plain,
    )
    options: list[OptionInput] | None = Field(
        default=None,
        max_length=10,
        description="For single and multiple: at least two options.",
        json_schema_extra=_plain,
    )
    accepted_answers: list[str] | None = Field(
        default=None,
        max_length=20,
        description="For text: accepted exact answers.",
        json_schema_extra=_plain,
    )
    regex: str | None = Field(
        default=None,
        max_length=200,
        description="For text: a regular expression.",
        json_schema_extra=_plain,
    )
    case_sensitive: bool = Field(
        default=False, description="For text: compare case-sensitively."
    )
    number: float | None = Field(
        default=None, description="For number: the right value."
    )
    tolerance: float = Field(
        default=0.0, ge=0, description="For number: allowed difference."
    )
    items: list[str] | None = Field(
        default=None,
        max_length=20,
        description="For sorting: items in order.",
        json_schema_extra=_plain,
    )
    pairs: list[PairInput] | None = Field(
        default=None,
        max_length=20,
        description="For matching: at least two pairs.",
        json_schema_extra=_plain,
    )
    rows: list[str] | None = Field(
        default=None, max_length=30, description="Table rows.", json_schema_extra=_plain
    )
    columns: list[str] | None = Field(
        default=None,
        max_length=30,
        description="Table columns.",
        json_schema_extra=_plain,
    )
    correct_cells: list[tuple[int, int]] | None = Field(
        default=None,
        description="For table: the (row, column) cells to mark, 0-based.",
        json_schema_extra=_plain,
    )
    blanks: list[BlankInput] | None = Field(
        default=None, max_length=20, json_schema_extra=_plain
    )
    variables: list[VariableInput] | None = Field(
        default=None,
        max_length=10,
        description="For random_number.",
        json_schema_extra=_plain,
    )
    formula: str | None = Field(
        default=None,
        max_length=500,
        description="For random_number: answer formula.",
        json_schema_extra=_plain,
    )
    expression: str | None = Field(
        default=None,
        max_length=500,
        description="For formula: the correct expression.",
        json_schema_extra=_plain,
    )
    expression_variables: list[str] | None = Field(
        default=None, max_length=10, json_schema_extra=_plain
    )
    expected_outputs: list[str] | None = Field(
        default=None, max_length=20, json_schema_extra=_plain
    )


class QuizSettingsInput(BaseModel):
    """Settings of a test block; omitted fields get the defaults shown."""

    max_attempts: int | None = Field(
        default=None, ge=1, le=100, description="Attempts per student; null: unlimited."
    )
    passing_score_pct: int = Field(default=60, ge=0, le=100)
    shuffle_questions: bool = False
    shuffle_options: bool = False
    pool_size: int | None = Field(
        default=None, ge=1, description="Ask N random questions of the pool; null: all."
    )
    time_limit_sec: int | None = Field(default=None, ge=30)
    cooldown_sec: int | None = Field(default=None, ge=0)
    show_answers: Literal[
        "never", "after_submit", "after_pass", "after_last_attempt"
    ] = "after_submit"


QuestionList = Annotated[
    list[QuestionInput],
    Field(max_length=50, description="Questions to add (at most 50)."),
]


# - - - Builders - - -


def build_text_block(markdown: str) -> dict[str, Any]:
    """Return a text block."""
    return {"id": "", "type": "text", "markdown": markdown}


def build_video_block(url: str, caption: str = "") -> dict[str, Any]:
    """Return a video block that plays a link.

    Raises:
        BlockInputError: The link is not an http(s) URL.
    """
    if not url.strip().lower().startswith(("https://", "http://")):
        raise BlockInputError("a video block needs an http(s) link in `url`")
    return {
        "id": "",
        "type": "video",
        "source": "link",
        "url": url.strip(),
        "file_id": None,
        "caption": caption,
    }


def build_flashcards_block(cards: list[FlashcardInput]) -> dict[str, Any]:
    """Return a flash cards block (cards belong to the course, not to a student)."""
    return {
        "id": "",
        "type": "flashcards",
        "cards": [{"id": "", "front": c.front, "back": c.back} for c in cards],
    }


def build_test_block(
    settings: QuizSettingsInput | None, questions: list[QuestionInput]
) -> dict[str, Any]:
    """Return a test block with its settings and questions.

    Raises:
        BlockInputError: A question breaks the rules of its type.
    """
    config = (settings or QuizSettingsInput()).model_dump()
    return {
        "id": "",
        "type": "test",
        "config": config,
        "questions": [build_question(question) for question in questions],
    }


def build_question(question: QuestionInput) -> dict[str, Any]:
    """Validate a question for its type and return it in the API shape.

    Raises:
        BlockInputError: The question breaks the rules of its type.
    """
    result: dict[str, Any] = {
        "id": "",
        "type": question.type,
        "prompt": question.prompt,
        "points": question.points,
        "explanation": question.explanation or None,
    }
    if question.type in ("single", "multiple"):
        result["options"] = _options(question)
    elif question.type == "text":
        result["answer"] = _text_answer(question)
    elif question.type == "number":
        result["answer"] = _number_answer(question)
    else:
        result.update(_task_fields(question))
    return result


def _task_fields(question: QuestionInput) -> dict[str, Any]:
    """Return the type-specific fields of the richer question types."""
    builder = _TASK_FIELDS.get(question.type)
    return {} if builder is None else builder(question)


def _sorting_fields(question: QuestionInput) -> dict[str, Any]:
    items = question.items or []
    if len(items) < 2:
        raise BlockInputError("a sorting question needs at least two items")
    return {"options": [{"id": "", "text": i, "correct": False} for i in items]}


def _matching_fields(question: QuestionInput) -> dict[str, Any]:
    pairs = question.pairs or []
    if len(pairs) < 2:
        raise BlockInputError("a matching question needs at least two pairs")
    return {"pairs": [{"id": "", "left": p.left, "right": p.right} for p in pairs]}


def _table_fields(question: QuestionInput) -> dict[str, Any]:
    rows, columns = question.rows or [], question.columns or []
    cells = set(question.correct_cells or [])
    if not rows or not columns or not cells:
        raise BlockInputError("a table question needs rows, columns and cells")
    if any(r >= len(rows) or c >= len(columns) or r < 0 or c < 0 for r, c in cells):
        raise BlockInputError("correct_cells point outside the table")
    grid = [[(r, c) in cells for c in range(len(columns))] for r in range(len(rows))]
    return {"table": {"rows": rows, "columns": columns, "correct": grid}}


def _blanks_fields(question: QuestionInput) -> dict[str, Any]:
    blanks = question.blanks or []
    if not blanks or any(not b.accepted and not b.regex for b in blanks):
        raise BlockInputError("each blank needs accepted answers or a regex")
    return {
        "blanks": [
            {"id": "", "accepted": b.accepted, "regex": b.regex or None} for b in blanks
        ]
    }


def _random_fields(question: QuestionInput) -> dict[str, Any]:
    if not question.variables or not (question.formula or "").strip():
        raise BlockInputError("random_number needs variables and a formula")
    if any(v.min > v.max for v in question.variables):
        raise BlockInputError("a variable has min above max")
    return {
        "random": {
            "variables": [v.model_dump() for v in question.variables],
            "formula": question.formula,
            "tolerance": question.tolerance,
        }
    }


def _formula_fields(question: QuestionInput) -> dict[str, Any]:
    if not (question.expression or "").strip():
        raise BlockInputError("a formula question needs `expression`")
    return {
        "formula": {
            "expression": question.expression,
            "variables": question.expression_variables or ["x"],
            "mode": "symbolic",
        }
    }


def _code_fields(question: QuestionInput) -> dict[str, Any]:
    return {"code": {"expected_outputs": question.expected_outputs or []}}


_TASK_FIELDS: Final[dict[str, Callable[[QuestionInput], dict[str, Any]]]] = {
    "sorting": _sorting_fields,
    "matching": _matching_fields,
    "table": _table_fields,
    "blanks": _blanks_fields,
    "random_number": _random_fields,
    "formula": _formula_fields,
    "code": _code_fields,
}


def _options(question: QuestionInput) -> list[dict[str, Any]]:
    options = question.options or []
    if len(options) < 2:
        raise BlockInputError("a choice question needs at least two options")
    correct = sum(1 for option in options if option.correct)
    if question.type == "single" and correct != 1:
        raise BlockInputError(
            "a single choice question needs exactly one correct option"
        )
    if question.type == "multiple" and correct < 1:
        raise BlockInputError("a multiple choice question needs a correct option")
    return [
        {"id": "", "text": o.text, "correct": o.correct, "pinned": o.pinned}
        for o in options
    ]


def _text_answer(question: QuestionInput) -> dict[str, Any]:
    accepted = question.accepted_answers or []
    if not accepted and not question.regex:
        raise BlockInputError("a text question needs accepted_answers or a regex")
    return {
        "accepted": accepted,
        "regex": question.regex or None,
        "case_sensitive": question.case_sensitive,
    }


def _number_answer(question: QuestionInput) -> dict[str, Any]:
    if question.number is None:
        raise BlockInputError("a number question needs the right value in `number`")
    return {"value": question.number, "tolerance": question.tolerance}


# - - - A whole step: what the author assistant and Studio produce - - -


class TextBlockInput(BaseModel):
    """A Markdown text block (LaTeX goes between ``$...$`` or ``$$...$$``)."""

    catalog: ClassVar[dict[str, Any]] = {
        "examples": [{"type": "text", "markdown": "# Title"}]
    }

    type: Literal["text"] = "text"
    markdown: str = Field(
        min_length=1,
        max_length=30_000,
        description="Markdown. Headings, lists, tables, code and LaTeX are allowed.",
    )


class TestBlockInput(BaseModel):
    """A test block: settings and questions."""

    __test__ = False  # not a pytest class, despite the name

    catalog: ClassVar[dict[str, Any]] = {
        "examples": [
            {
                "type": "test",
                "questions": [
                    {
                        "type": "single",
                        "prompt": "2 + 2?",
                        "options": [
                            {"text": "4", "correct": True},
                            {"text": "5"},
                        ],
                    }
                ],
            }
        ],
        "notes": "More questions can be added later with add_question.",
    }

    type: Literal["test"] = "test"
    settings: QuizSettingsInput | None = Field(
        default=None, description="Test settings; omit for the defaults."
    )
    questions: Annotated[list[QuestionInput], Field(min_length=1, max_length=50)]


class VideoBlockInput(BaseModel):
    """A video block: a link (YouTube, Vimeo or a direct file URL)."""

    catalog: ClassVar[dict[str, Any]] = {
        "examples": [{"type": "video", "url": "https://youtu.be/abc"}]
    }

    type: Literal["video"] = "video"
    url: str = Field(
        min_length=1, max_length=2000, description="Video link, https only."
    )
    caption: str = Field(default="", max_length=500, description="Caption, optional.")


class FlashcardsBlockInput(BaseModel):
    """A flash cards block."""

    catalog: ClassVar[dict[str, Any]] = {
        "examples": [{"type": "flashcards", "cards": [{"front": "Q", "back": "A"}]}],
        "notes": "The cards belong to the course, not to a student's own sets.",
    }

    type: Literal["flashcards"] = "flashcards"
    cards: CardList


BlockInput = Annotated[
    TextBlockInput | VideoBlockInput | TestBlockInput | FlashcardsBlockInput,
    Field(discriminator="type"),
]


class UploadedVideoBlockInput(BaseModel):
    """A video block that plays a lesson video uploaded to Files.

    Only for authors with a real upload: models never see this type, so they cannot
    invent a file ID.
    """

    catalog: ClassVar[dict[str, Any]] = {
        "examples": [
            {"type": "video_file", "file_id": "00000000-0000-0000-0000-000000000001"}
        ],
        "notes": (
            "file_id is a ready file uploaded with purpose lms_video (the web "
            "course editor or POST /v1/files). The upload_file tool stores "
            "chat attachments only and cannot make one."
        ),
    }

    type: Literal["video_file"] = "video_file"
    file_id: UUID = Field(
        description="ID of a ready file uploaded with purpose `lms_video`."
    )
    caption: str = Field(default="", max_length=500, description="Caption, optional.")


class H5PBlockInput(BaseModel):
    """An interactive H5P exercise (a package played in the browser)."""

    catalog: ClassVar[dict[str, Any]] = {
        "examples": [{"type": "h5p", "title": "Drag the words"}],
        "notes": (
            "package_id is the id of an H5P package uploaded in the course "
            "editor; no tool uploads H5P. Leave it out to add an empty block "
            "that a teacher fills in the editor."
        ),
    }

    type: Literal["h5p"] = "h5p"
    title: str = Field(default="", max_length=500, description="Exercise title.")
    package_id: UUID | None = Field(
        default=None, description="ID of an uploaded H5P package, if there is one."
    )
    main_library: str = Field(
        default="", max_length=200, description="H5P main library, e.g. H5P.Blanks."
    )
    passing_score_pct: float = Field(
        default=0.0, ge=0, le=100, description="Percent of points needed to pass."
    )


class InteractionInput(BaseModel):
    """A pause of an interactive video: a question, a note or a link."""

    at_sec: float = Field(ge=0, le=24 * 3600, description="Second of the pause.")
    kind: Literal["question", "note", "link"] = Field(
        default="question", description="What the pause shows."
    )
    text: str = Field(
        default="", max_length=2000, description="Question, note or link text."
    )
    options: list[OptionInput] = Field(
        default_factory=list,
        max_length=10,
        description="Answer options (question only).",
    )
    multiple: bool = Field(default=False, description="Several right options.")
    url: str = Field(default="", max_length=2000, description="Link target (http/s).")
    points: float = Field(default=1.0, ge=0, le=100, description="Score.")


class InteractiveVideoBlockInput(BaseModel):
    """A video that pauses at given seconds for questions, notes and links."""

    catalog: ClassVar[dict[str, Any]] = {
        "examples": [
            {
                "type": "interactive_video",
                "url": "https://www.youtube.com/watch?v=abc",
                "interactions": [
                    {
                        "at_sec": 30,
                        "kind": "question",
                        "text": "2 + 2?",
                        "options": [
                            {"text": "4", "correct": True},
                            {"text": "5"},
                        ],
                    }
                ],
            }
        ],
        "notes": (
            "Give a link in `url`, or `file_id` of a video uploaded to Files "
            "with purpose lms_video (the upload_file tool does not make one; "
            "use the web editor or POST /v1/files)."
        ),
    }

    type: Literal["interactive_video"] = "interactive_video"
    url: str = Field(default="", max_length=2000, description="Video link, http(s).")
    file_id: UUID | None = Field(
        default=None, description="ID of an uploaded video; replaces `url`."
    )
    caption: str = Field(default="", max_length=500, description="Caption.")
    interactions: list[InteractionInput] = Field(
        default_factory=list, max_length=100, description="Pauses of the video."
    )


class ExamModuleInput(BaseModel):
    """A timed module of an exam section."""

    title: str = Field(default="", max_length=200)
    time_limit_sec: int = Field(default=1920, ge=60, le=14_400)
    questions: list[QuestionInput] = Field(
        default_factory=list,
        max_length=200,
        description="Only single, multiple, number, text and free questions.",
    )


class ExamSectionInput(BaseModel):
    """A section of an exam: modules taken in order."""

    title: str = Field(default="", max_length=200)
    modules: list[ExamModuleInput] = Field(default_factory=list, max_length=4)
    adaptive: bool = Field(default=False, description="Module 2 depends on module 1.")


class ExamScalingInput(BaseModel):
    """The scaled score range of every section (SAT: 200 to 800)."""

    min_score: int = Field(default=200, ge=0, le=10_000)
    max_score: int = Field(default=800, ge=1, le=10_000)


class ExamBlockInput(BaseModel):
    """A Bluebook-style timed exam (SAT, AP or custom) with sections and modules."""

    catalog: ClassVar[dict[str, Any]] = {
        "examples": [
            {
                "type": "exam",
                "title": "Practice test",
                "sections": [
                    {
                        "title": "Math",
                        "modules": [
                            {
                                "time_limit_sec": 1800,
                                "questions": [
                                    {
                                        "type": "number",
                                        "prompt": "3 * 4",
                                        "number": 12,
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        ],
        "notes": "Questions use the same fields as in a test block.",
    }

    type: Literal["exam"] = "exam"
    title: str = Field(default="", max_length=200)
    kind: Literal["sat", "ap", "custom"] = "custom"
    directions: str = Field(default="", max_length=5000)
    reference_sheet: str = Field(default="", max_length=20_000)
    calculator: Literal["none", "scientific", "graphing"] = "none"
    sections: list[ExamSectionInput] = Field(default_factory=list, max_length=6)
    scaling: ExamScalingInput | None = Field(default=None)


class CodeTestInput(BaseModel):
    """A test of a code block; hidden tests show only their name to students."""

    name: str = Field(default="", max_length=200)
    code: str = Field(default="", max_length=5000)
    hidden: bool = False


class CodeBlockInput(BaseModel):
    """A runnable code panel with starter code, a solution and tests."""

    catalog: ClassVar[dict[str, Any]] = {
        "examples": [
            {
                "type": "code",
                "language": "python",
                "instructions": "Print the sum of 2 and 3.",
                "starter": "# your code",
                "tests": [{"name": "sum", "code": "assert True"}],
            }
        ]
    }

    type: Literal["code"] = "code"
    language: Literal["python", "javascript", "sql"] = "python"
    instructions: str = Field(default="", max_length=5000)
    starter: str = Field(default="", max_length=20_000)
    solution: str = Field(default="", max_length=20_000)
    tests: list[CodeTestInput] = Field(default_factory=list, max_length=30)
    time_limit_ms: int = Field(default=5000, ge=1000, le=30_000)
    graded: bool = False


class HtmlBlockInput(BaseModel):
    """A custom HTML widget, served in a sandbox."""

    catalog: ClassVar[dict[str, Any]] = {
        "examples": [{"type": "html", "title": "Pendulum", "height_px": 500}],
        "notes": (
            "package_id is the id of an HTML package uploaded in the course "
            "editor; no tool uploads it. Leave it out to add an empty widget "
            "that a teacher fills in the editor."
        ),
    }

    type: Literal["html"] = "html"
    title: str = Field(default="", max_length=200)
    package_id: UUID | None = Field(
        default=None, description="ID of an uploaded HTML package, if there is one."
    )
    height_px: int = Field(default=600, ge=200, le=2000)
    allow_fullscreen: bool = False
    graded: bool = False


class AiReviewCriterionInput(BaseModel):
    """One row of an AI review: a criterion and its top score."""

    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=1000)
    max_score: float = Field(default=10, ge=0, le=100)


class AiReviewFileInput(BaseModel):
    """A reference file for the reviewer; students never see its text."""

    file_id: UUID = Field(description="ID of a ready uploaded file.")
    name: str = Field(default="", max_length=200)


AiReviewFileKind = Literal["pdf", "docx", "pptx", "image", "text"]


class AiReviewBlockInput(BaseModel):
    """An AI reviewer of a student's submitted work, graded by criteria."""

    catalog: ClassVar[dict[str, Any]] = {
        "examples": [
            {
                "type": "ai_review",
                "title": "Project review",
                "instructions_public": "Upload your report.",
                "criteria": [{"name": "Clarity", "max_score": 10}],
            }
        ],
        "notes": "reference_files need ids of files already uploaded to Files.",
    }

    type: Literal["ai_review"] = "ai_review"
    title: str = Field(default="", max_length=200)
    instructions_public: str = Field(
        default="", max_length=10_000, description="Shown to students."
    )
    teacher_prompt: str = Field(
        default="", max_length=10_000, description="Private instructions."
    )
    output_template: Literal[
        "review_table", "rubric_checklist", "strengths_cards", "image_gallery"
    ] = "review_table"
    criteria: list[AiReviewCriterionInput] = Field(default_factory=list, max_length=20)
    use_course_materials: bool = True
    reference_files: list[AiReviewFileInput] = Field(
        default_factory=list, max_length=10
    )
    web_search: bool = False
    private_topics: list[Annotated[str, Field(max_length=200)]] = Field(
        default_factory=list, max_length=30
    )
    max_submissions: int = Field(default=3, ge=1, le=20)
    pass_threshold_pct: int = Field(default=60, ge=0, le=100)
    accepted_types: list[AiReviewFileKind] = Field(
        default_factory=lambda: list[AiReviewFileKind](
            ["pdf", "docx", "image", "text"]
        ),
        min_length=1,
    )


AuthorBlockInput = Annotated[
    TextBlockInput
    | VideoBlockInput
    | UploadedVideoBlockInput
    | TestBlockInput
    | FlashcardsBlockInput
    | H5PBlockInput
    | InteractiveVideoBlockInput
    | ExamBlockInput
    | CodeBlockInput
    | HtmlBlockInput
    | AiReviewBlockInput,
    Field(discriminator="type"),
]

AUTHOR_BLOCK_MODELS: Final[tuple[type[BaseModel], ...]] = get_args(
    get_args(AuthorBlockInput)[0]
)
"""Every block an author may create, derived from the union above."""


class StepDraftInput(BaseModel):
    """The content of one step as a model writes it (the ``lesson_draft`` output)."""

    title: str = Field(
        min_length=1, max_length=200, description="Step title, without numbering."
    )
    blocks: Annotated[
        list[BlockInput],
        Field(min_length=1, max_length=40, description="Blocks in reading order."),
    ]


def build_block(block: AuthorBlockInput) -> dict[str, Any]:
    """Return one block in the LMS shape.

    Raises:
        BlockInputError: The block breaks a rule of its type.
    """
    if isinstance(block, TextBlockInput):
        return build_text_block(block.markdown)
    if isinstance(block, VideoBlockInput):
        return build_video_block(block.url, block.caption)
    if isinstance(block, UploadedVideoBlockInput):
        return {
            "id": "",
            "type": "video",
            "source": "upload",
            "url": "",
            "file_id": str(block.file_id),
            "caption": block.caption,
        }
    if isinstance(block, FlashcardsBlockInput):
        return build_flashcards_block(block.cards)
    if isinstance(block, TestBlockInput):
        return build_test_block(block.settings, block.questions)
    return _build_rich_block(block)


def _build_rich_block(block: AuthorBlockInput) -> dict[str, Any]:
    """Return an h5p, interactive video, exam, code, html or AI review block."""
    if isinstance(block, H5PBlockInput):
        return {
            "id": "",
            "type": "h5p",
            "package_id": str(block.package_id or ""),
            "title": block.title,
            "main_library": block.main_library,
            "passing_score_pct": block.passing_score_pct,
        }
    if isinstance(block, InteractiveVideoBlockInput):
        return _interactive_video(block)
    if isinstance(block, ExamBlockInput):
        return _exam(block)
    if isinstance(block, CodeBlockInput):
        data = block.model_dump(exclude={"tests"})
        tests = [{"id": "", **t.model_dump()} for t in block.tests]
        return {"id": "", **data, "tests": tests}
    if isinstance(block, HtmlBlockInput):
        data = block.model_dump(exclude={"package_id"})
        return {
            "id": "",
            **data,
            "package_id": str(block.package_id or ""),
            "entry": "index.html",
        }
    if isinstance(block, AiReviewBlockInput):
        return _ai_review(block)
    raise BlockInputError(f"unsupported block type: {block.type}")


def _options_of(options: list[OptionInput]) -> list[dict[str, Any]]:
    """Return answer options in the API shape (ids left empty)."""
    return [
        {"id": "", "text": o.text, "correct": o.correct, "pinned": o.pinned}
        for o in options
    ]


def _interactive_video(block: InteractiveVideoBlockInput) -> dict[str, Any]:
    """Return an interactive video block."""
    if block.file_id is None:
        if not block.url.strip().lower().startswith(("https://", "http://")):
            raise BlockInputError("an interactive video needs `url` or `file_id`")
    for item in block.interactions:
        if item.kind == "question" and len(item.options) < 2:
            raise BlockInputError("a question pause needs at least two options")
    upload = block.file_id is not None
    return {
        "id": "",
        "type": "interactive_video",
        "source": "upload" if upload else "link",
        "url": "" if upload else block.url.strip(),
        "file_id": str(block.file_id) if upload else None,
        "caption": block.caption,
        "interactions": [
            {
                "id": "",
                "at_sec": i.at_sec,
                "kind": i.kind,
                "text": i.text,
                "options": _options_of(i.options),
                "multiple": i.multiple,
                "url": i.url,
                "points": i.points,
            }
            for i in block.interactions
        ],
    }


EXAM_QUESTION_TYPES: Final = frozenset({"single", "multiple", "number", "text", "free"})


def _exam(block: ExamBlockInput) -> dict[str, Any]:
    """Return an exam block; its questions follow the rules of a test."""
    if block.scaling and block.scaling.max_score <= block.scaling.min_score:
        raise BlockInputError("scaling max_score must be greater than min_score")
    sections: list[dict[str, Any]] = []
    for section in block.sections:
        modules: list[dict[str, Any]] = []
        for module in section.modules:
            for question in module.questions:
                if question.type not in EXAM_QUESTION_TYPES:
                    raise BlockInputError(
                        f"exam question type not allowed: {question.type}"
                    )
            modules.append(
                {
                    "id": "",
                    "title": module.title,
                    "time_limit_sec": module.time_limit_sec,
                    "questions": [build_question(q) for q in module.questions],
                }
            )
        sections.append(
            {
                "id": "",
                "title": section.title,
                "modules": modules,
                "adaptive": section.adaptive,
            }
        )
    data = block.model_dump(exclude={"sections", "scaling"})
    scaling = block.scaling.model_dump() if block.scaling else None
    return {"id": "", **data, "sections": sections, "scaling": scaling}


def _ai_review(block: AiReviewBlockInput) -> dict[str, Any]:
    """Return an AI review block."""
    data = block.model_dump(exclude={"reference_files"})
    files = [{"file_id": str(f.file_id), "name": f.name} for f in block.reference_files]
    return {"id": "", **data, "reference_files": files}


def build_step_content(draft: StepDraftInput) -> dict[str, Any]:
    """Return ``{"title", "blocks"}`` in the LMS ``StepContent`` shape (empty ids).

    Raises:
        BlockInputError: A test question breaks the rules of its type.
    """
    return {"title": draft.title, "blocks": [build_block(b) for b in draft.blocks]}


# - - - A course plan: sections, steps, learning goals - - -

Goal = Annotated[str, Field(min_length=1, max_length=300)]


class PlanStepInput(BaseModel):
    """One planned step."""

    title: str = Field(
        min_length=1, max_length=200, description="Step title, without numbering."
    )
    goals: list[Goal] = Field(
        default_factory=list,
        max_length=6,
        description="What a student can do after this step, one verb phrase each.",
    )
    summary: str = Field(
        default="",
        max_length=1200,
        description="What the step covers, how it is taught and checked.",
    )


class PlanSectionInput(BaseModel):
    """One planned section."""

    title: str = Field(min_length=1, max_length=200)
    goals: list[Goal] = Field(default_factory=list, max_length=6)
    steps: Annotated[list[PlanStepInput], Field(min_length=1, max_length=30)]


class CoursePlanInput(BaseModel):
    """A plan of a course (the ``course_plan`` output); the author may edit it."""

    summary: str = Field(default="", max_length=2000, description="Course overview.")
    goals: list[Goal] = Field(
        default_factory=list, max_length=10, description="Course learning outcomes."
    )
    sections: Annotated[list[PlanSectionInput], Field(min_length=1, max_length=30)]


_BRIEF_LABELS: dict[str, tuple[str, str]] = {
    "en": ("Learning goals", "Plan"),
    "ru": ("Цели обучения", "План"),
    "uz": ("O'quv maqsadlari", "Reja"),
}


def step_brief(step: PlanStepInput, language: str) -> str:
    """Return a planned step as the Markdown of its first text block."""
    goals_label, plan_label = _BRIEF_LABELS.get(language, _BRIEF_LABELS["en"])
    parts: list[str] = []
    if step.goals:
        parts.append(f"**{goals_label}**\n\n" + "\n".join(f"- {g}" for g in step.goals))
    if step.summary:
        parts.append(f"**{plan_label}**\n\n{step.summary}")
    return "\n\n".join(parts)


def outline_sections(
    plan: CoursePlanInput, language: str = "en"
) -> list[dict[str, Any]]:
    """Return the plan as the ``sections`` argument of ``apply_outline``.

    Every step carries its ``brief`` (goals and summary as Markdown); the caller
    decides with ``add_briefs`` whether new steps get it as a first text block.
    """
    return [
        {
            "title": section.title,
            "steps": [
                {"title": step.title, "brief": step_brief(step, language)}
                for step in section.steps
            ],
        }
        for section in plan.sections
    ]
