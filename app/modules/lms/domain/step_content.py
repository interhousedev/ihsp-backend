"""Step content: the JSON document of a course step (README -> Course versioning)."""

import copy
import hashlib
import json
import secrets
from collections.abc import Iterator
from typing import Annotated, Literal

from pydantic import BaseModel, Field

ShowAnswers = Literal["never", "after_submit", "after_pass", "after_last_attempt"]
QuestionType = Literal["single", "multiple", "text", "number"]


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


class Question(BaseModel):
    """A test question."""

    id: str = ""
    type: QuestionType
    prompt: str
    points: float = 1.0
    explanation: str | None = None
    options: list[Option] | None = None
    answer: AnswerConfig | None = None


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


class FlashcardsBlock(BaseModel):
    """A block of flash cards studied with spaced repetition."""

    id: str = ""
    type: Literal["flashcards"] = "flashcards"
    cards: list[Card] = Field(default_factory=list)


Block = Annotated[TextBlock | TestBlock | FlashcardsBlock, Field(discriminator="type")]


Identified = TextBlock | TestBlock | FlashcardsBlock | Question | Option | Card


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
