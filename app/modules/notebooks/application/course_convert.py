"""Conversions of Studio outputs into the blocks and the outline of an LMS course.

Pure functions over the stored `content` of an output (or over the plan or the lesson
the author edited in the viewer). Everything that goes into a course passes through
the shared block contracts (`app.shared.contracts.lms_blocks`), so the rules of the
LMS are checked here, before anything is written, and the students never see a
passage label.

Whatever a quiz or a deck holds that an LMS block cannot express is reduced and
reported in a note: true/false questions become single choice questions with two
options, hints and topics are not copied.
"""

from dataclasses import dataclass, field
from typing import Any

from app.modules.notebooks.domain.artifacts.course_text import (
    clean_lesson_markdown,
    strip_ref_labels,
)
from app.shared.contracts.lms_blocks import (
    BlockInputError,
    CoursePlanInput,
    FlashcardInput,
    FlashcardsBlockInput,
    OptionInput,
    PlanSectionInput,
    PlanStepInput,
    QuestionInput,
    StepDraftInput,
    TestBlockInput,
    TextBlockInput,
    build_flashcards_block,
    build_step_content,
    build_test_block,
    outline_sections,
)

from pydantic import ValidationError

DEFAULT_LANGUAGE = "en"


@dataclass(frozen=True, slots=True)
class Converted:
    """Blocks in the LMS shape (empty ids) and what was reduced on the way."""

    blocks: list[dict[str, Any]]
    notes: list[str] = field(default_factory=list)


def _line(text: object) -> str:
    """A text of a question or a card without labels, on trimmed lines."""
    return strip_ref_labels(str(text or "")).strip()


# - - - Quiz -> test block - - -


def _choice_question(number: int, raw: dict[str, Any]) -> QuestionInput:
    """One `single`, `multiple` or `true_false` question as a choice question."""
    correct = {str(item) for item in raw.get("correct") or []}
    options = [
        OptionInput(
            text=_line(option.get("text")), correct=str(option.get("id")) in correct
        )
        for option in raw.get("options") or []
        if isinstance(option, dict)
    ]
    kind = "multiple" if raw.get("type") == "multiple" else "single"
    try:
        return QuestionInput(
            type=kind,
            prompt=_line(raw.get("prompt")),
            explanation=_line(raw.get("explanation")) or None,
            options=options,
        )
    except ValidationError as exc:
        raise BlockInputError(f"question {number}: {exc.errors()[0]['msg']}") from exc


def quiz_to_questions(content: dict[str, Any]) -> tuple[list[QuestionInput], list[str]]:
    """The questions of a quiz as LMS questions, and the notes about what changed.

    Raises:
        BlockInputError: The quiz has no question or one of them breaks a rule.
    """
    raw_questions = [q for q in content.get("questions") or [] if isinstance(q, dict)]
    questions = [_choice_question(n, q) for n, q in enumerate(raw_questions, start=1)]
    notes: list[str] = []
    flat = sum(1 for q in raw_questions if q.get("type") == "true_false")
    if flat:
        notes.append(
            f"{flat} true/false question(s) became single choice questions with "
            "two options."
        )
    hints = sum(1 for q in raw_questions if q.get("hint"))
    if hints:
        notes.append(f"The hints of {hints} question(s) were not copied.")
    if not questions:
        raise BlockInputError("the quiz has no questions")
    return questions, notes


def quiz_to_blocks(content: dict[str, Any]) -> Converted:
    """A quiz as one test block with the default settings.

    Raises:
        BlockInputError: The quiz is empty or breaks a question rule.
    """
    questions, notes = quiz_to_questions(content)
    return Converted([build_test_block(None, questions)], notes)


# - - - Flash cards -> flash cards block - - -


def deck_to_cards(content: dict[str, Any]) -> tuple[list[FlashcardInput], list[str]]:
    """The cards of a deck as LMS cards, and the notes about what changed.

    Raises:
        BlockInputError: The deck has no usable card.
    """
    raw_cards = [c for c in content.get("cards") or [] if isinstance(c, dict)]
    cards: list[FlashcardInput] = []
    for raw in raw_cards:
        front, back = _line(raw.get("front")), _line(raw.get("back"))
        if front and back:
            cards.append(FlashcardInput(front=front, back=back))
    if not cards:
        raise BlockInputError("the deck has no usable cards")
    notes: list[str] = []
    if any(c.get("hint") or c.get("topic") for c in raw_cards):
        notes.append("The hints and topics of the cards were not copied.")
    return cards, notes


def deck_to_blocks(content: dict[str, Any]) -> Converted:
    """A deck as one flash cards block.

    Raises:
        BlockInputError: The deck has no usable card.
    """
    cards, notes = deck_to_cards(content)
    return Converted([build_flashcards_block(cards)], notes)


# - - - Lesson draft -> step content - - -


def clean_draft(draft: StepDraftInput) -> StepDraftInput:
    """The draft with clean Markdown and texts (the author may have edited them).

    Raises:
        BlockInputError: A block is empty once the labels are removed.
    """
    blocks: list[TextBlockInput | TestBlockInput | FlashcardsBlockInput] = []
    for block in draft.blocks:
        if isinstance(block, TextBlockInput):
            markdown = clean_lesson_markdown(block.markdown)
            if not markdown:
                raise BlockInputError("a text block has no text")
            blocks.append(TextBlockInput(markdown=markdown))
        elif isinstance(block, FlashcardsBlockInput):
            cards = [
                FlashcardInput(front=_line(c.front), back=_line(c.back))
                for c in block.cards
            ]
            blocks.append(FlashcardsBlockInput(cards=cards))
        else:
            blocks.append(block)
    title = " ".join(strip_ref_labels(draft.title).split())
    try:
        return StepDraftInput(title=title or draft.title, blocks=blocks)
    except ValidationError as exc:
        raise BlockInputError(exc.errors()[0]["msg"]) from exc


def draft_of(content: dict[str, Any]) -> StepDraftInput:
    """The stored `lesson_draft` content as the contract model.

    Raises:
        BlockInputError: The content does not match the contract.
    """
    try:
        return StepDraftInput.model_validate(content)
    except ValidationError as exc:
        error = exc.errors(include_url=False, include_input=False)[0]
        where = ".".join(str(part) for part in error["loc"])
        raise BlockInputError(f"{where}: {error['msg']}") from exc


def draft_to_content(draft: StepDraftInput) -> dict[str, Any]:
    """The draft as ``{"title", "blocks"}`` in the LMS shape (empty ids).

    Raises:
        BlockInputError: A test question breaks the rules of its type.
    """
    return build_step_content(clean_draft(draft))


# - - - Course plan -> outline - - -


def plan_of(content: dict[str, Any]) -> CoursePlanInput:
    """The stored `course_plan` content as the contract model.

    Raises:
        BlockInputError: The content does not match the contract.
    """
    try:
        return CoursePlanInput.model_validate(content)
    except ValidationError as exc:
        error = exc.errors(include_url=False, include_input=False)[0]
        where = ".".join(str(part) for part in error["loc"])
        raise BlockInputError(f"{where}: {error['msg']}") from exc


def _plain(text: str) -> str:
    """A one-line text without passage labels."""
    return " ".join(strip_ref_labels(text).split())


def clean_plan(plan: CoursePlanInput) -> CoursePlanInput:
    """The plan without labels in any text (the author may have edited it).

    Raises:
        BlockInputError: A title or a goal is empty once the labels are removed.
    """
    try:
        return CoursePlanInput(
            summary=_plain(plan.summary),
            goals=[_plain(goal) for goal in plan.goals],
            sections=[
                PlanSectionInput(
                    title=_plain(section.title),
                    goals=[_plain(goal) for goal in section.goals],
                    steps=[
                        PlanStepInput(
                            title=_plain(step.title),
                            goals=[_plain(goal) for goal in step.goals],
                            summary=_plain(step.summary),
                        )
                        for step in section.steps
                    ],
                )
                for section in plan.sections
            ],
        )
    except ValidationError as exc:
        raise BlockInputError(exc.errors()[0]["msg"]) from exc


def plan_to_sections(plan: CoursePlanInput, language: str) -> list[dict[str, Any]]:
    """The plan as the ``sections`` argument of ``apply_outline`` (with the briefs).

    Raises:
        BlockInputError: A title or a goal is empty once the labels are removed.
    """
    return outline_sections(clean_plan(plan), language or DEFAULT_LANGUAGE)
