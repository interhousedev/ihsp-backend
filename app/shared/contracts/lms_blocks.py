"""Input models and builders of LMS step blocks, shared by the MCP server and the AI.

The LMS Course MCP server and the course author assistant add the same kinds of blocks
(Markdown text, tests, flash cards) to a draft step. The argument models below are
what both show to a model as a JSON schema, and the builders turn them into blocks in
the shape of the LMS ``Block`` contract. Ids are left empty: the server assigns random
ids to blocks, questions, options and cards (LMS-23).
"""

from collections.abc import Callable
from typing import Annotated, Any, Final, Literal

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

    type: Literal["text"] = "text"
    markdown: str = Field(
        min_length=1,
        max_length=30_000,
        description="Markdown. Headings, lists, tables, code and LaTeX are allowed.",
    )


class TestBlockInput(BaseModel):
    """A test block: settings and questions."""

    __test__ = False  # not a pytest class, despite the name

    type: Literal["test"] = "test"
    settings: QuizSettingsInput | None = Field(
        default=None, description="Test settings; omit for the defaults."
    )
    questions: Annotated[list[QuestionInput], Field(min_length=1, max_length=50)]


class VideoBlockInput(BaseModel):
    """A video block: a link (YouTube, Vimeo or a direct file URL)."""

    type: Literal["video"] = "video"
    url: str = Field(
        min_length=1, max_length=2000, description="Video link, https only."
    )
    caption: str = Field(default="", max_length=500, description="Caption, optional.")


class FlashcardsBlockInput(BaseModel):
    """A flash cards block."""

    type: Literal["flashcards"] = "flashcards"
    cards: CardList


BlockInput = Annotated[
    TextBlockInput | VideoBlockInput | TestBlockInput | FlashcardsBlockInput,
    Field(discriminator="type"),
]


class StepDraftInput(BaseModel):
    """The content of one step as a model writes it (the ``lesson_draft`` output)."""

    title: str = Field(
        min_length=1, max_length=200, description="Step title, without numbering."
    )
    blocks: Annotated[
        list[BlockInput],
        Field(min_length=1, max_length=40, description="Blocks in reading order."),
    ]


def build_block(block: BlockInput) -> dict[str, Any]:
    """Return one block in the LMS shape.

    Raises:
        BlockInputError: A test question breaks the rules of its type.
    """
    if isinstance(block, TextBlockInput):
        return build_text_block(block.markdown)
    if isinstance(block, VideoBlockInput):
        return build_video_block(block.url, block.caption)
    if isinstance(block, FlashcardsBlockInput):
        return build_flashcards_block(block.cards)
    return build_test_block(block.settings, block.questions)


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
