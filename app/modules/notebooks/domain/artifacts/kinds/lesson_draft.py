"""Lesson draft (course workspaces): the blocks of one step of a course.

The model writes the blocks in a flat shape (no unions, which strict structured output
handles badly); `process` turns every block into the matching `*BlockInput` of the LMS
block contracts and runs `build_step_content` over the result, so the question rules
of the LMS (one right option, an answer for a text or number question, ...) are checked
here and not when the author presses Apply.

What the author sees is never marked up with sources: the Markdown is cleaned of
passage labels, raw HTML, images and links, headings start at ``###``, and the refs of
a block are kept in a separate `refs` list (shown as chips by the viewer).
A broken question or card is dropped and noted in `notes`; a lesson without text, a
missing requested test or cards block, a placeholder text are sent back for repair.
"""

import random
from dataclasses import dataclass
from typing import Any, Final, Literal
from uuid import UUID

from app.modules.notebooks.domain.artifacts.course_text import (
    clean_item_title,
    clean_lesson_markdown,
    find_placeholder,
    strip_ref_labels,
)
from app.modules.notebooks.domain.artifacts.handler import (
    ArtifactHandler,
    ProcessContext,
    ProcessedOutput,
)
from app.modules.notebooks.domain.artifacts.kind_support import (
    CommonOptions,
    document_title,
    dump_options,
    expect_options,
    fit_text,
    norm_key,
    parse_options,
    require_list,
    validate_numbered,
)
from app.modules.notebooks.domain.artifacts.refs import build_refs_index, valid_refs
from app.modules.notebooks.domain.artifacts.strict import to_strict_schema
from app.modules.notebooks.domain.enums import ArtifactKind
from app.modules.notebooks.domain.errors import OutputInvalidError
from app.modules.notebooks.domain.limits import ARTIFACT_TITLE_MAX_CHARS
from app.modules.notebooks.domain.prompts.course import TOPIC_MAX_CHARS, lesson_task
from app.shared.contracts.lms_blocks import (
    BlockInputError,
    FlashcardInput,
    FlashcardsBlockInput,
    OptionInput,
    QuestionInput,
    StepDraftInput,
    TestBlockInput,
    TextBlockInput,
    build_question,
    build_step_content,
)

from pydantic import BaseModel, Field, ValidationError, field_validator

SCHEMA_NAME: Final = "nb_lesson_draft"
Length = Literal["short", "standard", "long"]
WORDS: Final = {"short": 300, "standard": 600, "long": 1_000}
QUESTIONS: Final = {"short": 4, "standard": 6, "long": 8}
CARDS: Final = {"short": 6, "standard": 10, "long": 15}
MAX_TOKENS: Final = {"short": 3_500, "standard": 5_500, "long": 8_500}
TEST_EXTRA_TOKENS: Final = 1_800
CARDS_EXTRA_TOKENS: Final = 1_200
MIN_TEXT_CHARS: Final = 200
TITLE_CHARS: Final = 200
MAX_BLOCKS: Final = 40
PROMPT_CHARS: Final = 2_000
OPTION_CHARS: Final = 500
EXPLANATION_CHARS: Final = 2_000
CARD_CHARS: Final = 2_000
MAX_OPTIONS: Final = 10
MAX_ACCEPTED: Final = 20
FALLBACK_TITLE: Final = "Lesson draft"
_CHOICE: Final = ("single", "multiple")

Block = TextBlockInput | TestBlockInput | FlashcardsBlockInput


class LessonDraftOptions(CommonOptions):
    """Options of a lesson draft; no `step_id` means a new step."""

    step_id: UUID | None = None
    topic: str | None = Field(default=None, max_length=TOPIC_MAX_CHARS)
    include_test: bool = False
    include_flashcards: bool = False
    length: Length = "standard"

    @field_validator("topic")
    @classmethod
    def _blank_topic_is_none(cls, value: str | None) -> str | None:
        """An empty or blank topic means no topic."""
        return (value or "").strip() or None


class OptionOut(BaseModel):
    """An answer option of a choice question."""

    text: str
    correct: bool


class QuestionOut(BaseModel):
    """A test question as the model writes it (the fields of its `type` only)."""

    type: Literal["single", "multiple", "text", "number"]
    prompt: str
    explanation: str | None = Field(
        default=None, description="why the right answer is right, 1 to 3 sentences"
    )
    options: list[OptionOut] | None = Field(
        default=None, description="single and multiple only"
    )
    accepted_answers: list[str] | None = Field(
        default=None, description="text only: every acceptable answer, lowercase"
    )
    number: float | None = Field(default=None, description="number only: the answer")
    tolerance: float | None = Field(
        default=None, description="number only: allowed difference, 0 for exact"
    )


class CardOut(BaseModel):
    """A flash card as the model writes it."""

    front: str
    back: str


class LessonBlockOut(BaseModel):
    """One block; fill the fields of its `type` and leave the others null."""

    type: Literal["text", "test", "flashcards"]
    markdown: str | None = Field(
        default=None, description="text blocks: the Markdown, headings from ###"
    )
    questions: list[QuestionOut] | None = Field(
        default=None, description="test blocks: the questions"
    )
    cards: list[CardOut] | None = Field(
        default=None, description="flashcards blocks: the cards"
    )
    refs: list[str] | None = Field(
        default=None, description="passage labels such as S1:P4 the block relies on"
    )


class LessonDraftOut(BaseModel):
    """The JSON document of the model (`nb_lesson_draft`)."""

    title: str = Field(description="what the lesson is about, a short noun phrase")
    blocks: list[LessonBlockOut]


@dataclass(slots=True)
class _Built:
    """A block that passed the contract, with the labels it relies on."""

    block: Block
    refs: list[str]


@dataclass(slots=True)
class _Report:
    """What the checks found: `hard` sends the document back, `notes` do not."""

    hard: list[str]
    notes: list[str]


def _reason(exc: ValueError) -> str:
    """Why a question or card was refused, in one short sentence."""
    if isinstance(exc, ValidationError):
        error = exc.errors(include_url=False, include_input=False)[0]
        where = ".".join(str(part) for part in error["loc"])
        return f"{where}: {error['msg']}"
    return str(exc)


# - - - Questions and cards - - -


def _options_of(item: QuestionOut, shuffle_seed: str) -> list[OptionInput] | None:
    """Choice options, distinct and shuffled with a seed (models favour A and B)."""
    if item.type not in _CHOICE:
        return None
    options: dict[str, OptionInput] = {}
    for option in item.options or []:
        text = fit_text(strip_ref_labels(option.text), chars=OPTION_CHARS)
        if text:
            options.setdefault(
                norm_key(text), OptionInput(text=text, correct=bool(option.correct))
            )
    shuffled = list(options.values())[:MAX_OPTIONS]
    random.Random(shuffle_seed).shuffle(shuffled)
    return shuffled


def _question(item: QuestionOut, shuffle_seed: str) -> QuestionInput:
    """One question in the LMS contract; raises `ValueError` when it is broken."""
    prompt = fit_text(strip_ref_labels(item.prompt), chars=PROMPT_CHARS)
    explanation = fit_text(
        strip_ref_labels(item.explanation or ""), chars=EXPLANATION_CHARS
    )
    accepted = [
        fit_text(answer, chars=OPTION_CHARS) for answer in item.accepted_answers or []
    ]
    question = QuestionInput(
        type=item.type,
        prompt=prompt,
        explanation=explanation or None,
        options=_options_of(item, shuffle_seed),
        accepted_answers=[a for a in accepted if a][:MAX_ACCEPTED] or None,
        number=item.number if item.type == "number" else None,
        tolerance=abs(item.tolerance or 0.0),
    )
    placeholder = find_placeholder(f"{prompt} {explanation}")
    if placeholder:
        raise BlockInputError(f"remove the placeholder {placeholder!r}")
    build_question(question)
    return question


def _questions(
    items: list[QuestionOut], seed: int, notes: list[str]
) -> list[QuestionInput]:
    """The valid, distinct questions of a test block; the others are noted."""
    found: dict[str, QuestionInput] = {}
    for number, item in enumerate(items, start=1):
        try:
            question = _question(item, f"{seed}:{number}")
        except ValueError as exc:
            notes.append(f"test question {number} was dropped: {_reason(exc)}")
            continue
        found.setdefault(norm_key(question.prompt), question)
    return list(found.values())


def _cards(items: list[CardOut], notes: list[str]) -> list[FlashcardInput]:
    """The valid, distinct cards of a flash cards block; the others are noted."""
    found: dict[str, FlashcardInput] = {}
    for number, item in enumerate(items, start=1):
        front = fit_text(strip_ref_labels(item.front), chars=CARD_CHARS)
        back = fit_text(strip_ref_labels(item.back), chars=CARD_CHARS)
        if not front or not back or find_placeholder(f"{front} {back}"):
            notes.append(f"card {number} was dropped: empty side or a placeholder")
            continue
        found.setdefault(norm_key(front), FlashcardInput(front=front, back=back))
    return list(found.values())


# - - - Blocks - - -


def _text_block(raw: LessonBlockOut, number: int, report: _Report) -> Block | None:
    """A text block with clean Markdown, or None (a hard problem is recorded)."""
    markdown = clean_lesson_markdown(raw.markdown or "")
    if not markdown:
        report.hard.append(f"block {number}: a text block needs `markdown`")
        return None
    placeholder = find_placeholder(markdown)
    if placeholder:
        report.hard.append(
            f"block {number}: remove the placeholder {placeholder!r} and write the text"
        )
        return None
    return TextBlockInput(markdown=markdown)


def _build_block(
    raw: LessonBlockOut, number: int, seed: int, report: _Report
) -> Block | None:
    """One block of the contract, or None when it is empty or refused."""
    if raw.type == "text":
        return _text_block(raw, number, report)
    if raw.type == "test":
        questions = _questions(raw.questions or [], seed, report.notes)
        return TestBlockInput(questions=questions) if questions else None
    cards = _cards(raw.cards or [], report.notes)
    return FlashcardsBlockInput(cards=cards) if cards else None


def _build_blocks(
    data: dict[str, Any], ctx: ProcessContext, report: _Report
) -> list[_Built]:
    """Every usable block of the document, in order (at most 40)."""
    items = validate_numbered(
        LessonBlockOut, require_list(data, "blocks"), report.hard, "block"
    )
    built: list[_Built] = []
    for number, raw in items:
        block = _build_block(raw, number, ctx.seed, report)
        if block is not None:
            built.append(_Built(block, valid_refs(raw.refs or [], ctx.pack)))
    return built[:MAX_BLOCKS]


def _wanted(
    built: list[_Built], opts: LessonDraftOptions, report: _Report
) -> list[_Built]:
    """Keep the blocks that were asked for; an unrequested test or cards is dropped."""
    kept: list[_Built] = []
    for item in built:
        asked = {
            "test": opts.include_test,
            "flashcards": opts.include_flashcards,
        }.get(item.block.type, True)
        if asked:
            kept.append(item)
        else:
            report.notes.append(
                f"a {item.block.type} block was not asked for and dropped"
            )
    return kept


def _check_text(built: list[_Built], report: _Report) -> None:
    """The lesson has text, and enough of it."""
    texts = [b.block for b in built if isinstance(b.block, TextBlockInput)]
    if not texts:
        report.hard.append("the lesson needs at least one text block with the lesson")
        return
    if sum(len(block.markdown) for block in texts) < MIN_TEXT_CHARS:
        report.hard.append(
            f"the lesson text is too short: write at least {MIN_TEXT_CHARS} characters"
        )


def _check_test(built: list[_Built], opts: LessonDraftOptions, report: _Report) -> None:
    """A requested test block has enough valid questions."""
    tests = [b.block for b in built if isinstance(b.block, TestBlockInput)]
    needed = max(2, QUESTIONS[opts.length] // 2)
    if opts.include_test and sum(len(t.questions) for t in tests) < needed:
        report.hard.append(
            f"a test block with at least {needed} valid questions is required"
        )


def _check_cards(
    built: list[_Built], opts: LessonDraftOptions, report: _Report
) -> None:
    """A requested flash cards block has enough valid cards."""
    decks = [b.block for b in built if isinstance(b.block, FlashcardsBlockInput)]
    needed = max(3, CARDS[opts.length] // 2)
    if opts.include_flashcards and sum(len(d.cards) for d in decks) < needed:
        report.hard.append(
            f"a flashcards block with at least {needed} cards is required"
        )


def _check_parts(
    built: list[_Built], opts: LessonDraftOptions, report: _Report
) -> None:
    """The lesson has text, and the test and the cards that were asked for."""
    _check_text(built, report)
    _check_test(built, opts, report)
    _check_cards(built, opts, report)


class LessonDraftHandler:
    """Options, prompt, schema and validation of the lesson draft."""

    kind: ArtifactKind = ArtifactKind.LESSON_DRAFT
    schema_name: str = SCHEMA_NAME

    def parse_options(self, raw: dict[str, Any]) -> BaseModel:
        """Validate the request's options."""
        return parse_options(LessonDraftOptions, raw)

    def stored_options(self, options: BaseModel) -> dict[str, Any]:
        """Options with defaults filled (no `step_id`: a new step)."""
        return dump_options(expect_options(options, LessonDraftOptions))

    def report_format(self, options: BaseModel) -> str | None:
        """A lesson has no report format."""
        return None

    def max_tokens(self, options: BaseModel) -> int:
        """3 500 / 5 500 / 8 500 by length, plus room for a test and for cards."""
        opts = expect_options(options, LessonDraftOptions)
        extra = TEST_EXTRA_TOKENS if opts.include_test else 0
        extra += CARDS_EXTRA_TOKENS if opts.include_flashcards else 0
        return MAX_TOKENS[opts.length] + extra

    def input_cap_tokens(self, studio_context_tokens: int) -> int:
        """The Studio context cap."""
        return studio_context_tokens

    def strict_schema(self) -> dict[str, Any]:
        """The strict schema of `LessonDraftOut`."""
        return to_strict_schema(LessonDraftOut)

    def task_block(self, options: BaseModel, prompt: str | None) -> str:
        """The English task text (the course part is added by the engine)."""
        opts = expect_options(options, LessonDraftOptions)
        return lesson_task(
            words=WORDS[opts.length],
            topic=opts.topic,
            include_test=opts.include_test,
            include_flashcards=opts.include_flashcards,
            questions=QUESTIONS[opts.length],
            cards=CARDS[opts.length],
            prompt=prompt,
        )

    def default_title(self, notebook_title: str, options: BaseModel) -> str:
        """The topic, else ``Lesson draft: <notebook>``."""
        topic = expect_options(options, LessonDraftOptions).topic
        return (topic or f"{FALLBACK_TITLE}: {notebook_title}")[
            :ARTIFACT_TITLE_MAX_CHARS
        ]

    def process(
        self, data: dict[str, Any], options: BaseModel, ctx: ProcessContext
    ) -> ProcessedOutput:
        """Build and check the blocks, clean the Markdown, resolve refs.

        Raises:
            OutputInvalidError: No text, a requested part is missing, a placeholder
                is left or the contract refuses the document.
        """
        opts = expect_options(options, LessonDraftOptions)
        report = _Report(hard=[], notes=[])
        built = _wanted(_build_blocks(data, ctx, report), opts, report)
        _check_parts(built, opts, report)
        if report.hard:
            raise OutputInvalidError([*report.hard, *report.notes])
        title = _lesson_title(data, opts, ctx)
        draft = StepDraftInput(title=title, blocks=[item.block for item in built])
        try:
            build_step_content(draft)
        except BlockInputError as exc:
            raise OutputInvalidError([str(exc)]) from exc
        content = draft.model_dump(mode="json", exclude_none=True)
        for dumped, item in zip(content["blocks"], built, strict=True):
            dumped["refs"] = item.refs
        content["language"] = ctx.language
        content["notes"] = report.notes
        return ProcessedOutput(
            title=title,
            content=content,
            refs_index=build_refs_index((b.refs for b in built), ctx.pack),
        )


def _lesson_title(
    data: dict[str, Any], opts: LessonDraftOptions, ctx: ProcessContext
) -> str:
    """The model's title, else the topic, the step's title or the first source's."""
    title = clean_item_title(data.get("title"), TITLE_CHARS)
    if title:
        return title
    course = ctx.pack.course
    named = opts.topic or (course.step_title if course else None)
    return clean_item_title(named, TITLE_CHARS) or document_title(
        {}, ctx.pack, FALLBACK_TITLE
    )


HANDLER: ArtifactHandler = LessonDraftHandler()
