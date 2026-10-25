"""Step content as readable text for notebook sources.

Every block becomes a labelled, model-friendly piece of text: text blocks keep their
Markdown, flash cards become ``Front: … / Back: …`` cards, videos their caption and
address, and test blocks their questions. A student's copy (the default) never holds
correctness data: question prompts and answer options only, in the order the author
wrote them, with sorting items and matching halves listed alphabetically so the order
reveals nothing (LMS-17: correct answers and explanations never reach the browser
before an attempt is graded). ``with_answers=True`` is for the course workspace of the
teachers who wrote the test: it adds the correct options, accepted answers and
explanations.
"""

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final
from uuid import UUID

from app.modules.lms.domain.authoring.content_edit import FILE_REFERENCE
from app.modules.lms.domain.step_content import (
    FlashcardsBlock,
    Question,
    StepContent,
    TestBlock,
    TextBlock,
    VideoBlock,
)

BLOCK_SEPARATOR = "\n\n"
# A link to a library book or material (`/item?id=<uuid>` or `/read?id=<uuid>`).
LIBRARY_REFERENCE: Final = re.compile(
    r"/(?:item|read)\?(?:[^\s)\"'&]*&)*(?:id|item)=([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})"
)
_BLANK: Final = re.compile(r"\{\{\s*\d+\s*\}\}")
_LETTERS: Final = "abcdefghijklmnopqrstuvwxyz"
_TYPE_NAMES: Final = {
    "single": "single choice",
    "multiple": "multiple choice",
    "text": "short text",
    "number": "number",
    "sorting": "put in order",
    "matching": "matching",
    "table": "table",
    "blanks": "fill in the blanks",
    "random_number": "number",
    "formula": "formula",
    "free": "free answer",
    "code": "code",
}


def export_text(
    content: StepContent, *, with_answers: bool = False
) -> tuple[str, tuple[int, ...]]:
    """Return the readable text of a step and where each exported block starts.

    Text blocks give their Markdown; flash card blocks ``Card n / Front / Back``
    lines; test blocks ``Question n (type): prompt`` with the options; videos are
    skipped here (they are their own sources). Blocks without text are skipped, so
    an empty step gives ``("", ())``.

    Args:
        content: The step.
        with_answers: Add correct answers and explanations (course workspace only).

    Returns:
        The blocks joined by a blank line, and the character offset of every
        exported block in that text.
    """
    pieces = [
        piece for block in content.blocks if (piece := _piece(block, with_answers))
    ]
    starts: list[int] = []
    offset = 0
    for piece in pieces:
        starts.append(offset)
        offset += len(piece) + len(BLOCK_SEPARATOR)
    return BLOCK_SEPARATOR.join(pieces), tuple(starts)


def _piece(block: object, with_answers: bool) -> str:
    """Return the text of one block, or '' for blocks that are not exported."""
    if isinstance(block, TextBlock):
        return block.markdown.strip()
    if isinstance(block, FlashcardsBlock):
        return _cards_text(block)
    if isinstance(block, TestBlock):
        return _test_text(block, with_answers)
    return ""


def _one_line(text: str) -> str:
    """Collapse whitespace so a prompt or option stays on its line."""
    return " ".join(text.split())


def _cards_text(block: FlashcardsBlock) -> str:
    """``Flash cards: N cards.`` then one ``Card n`` paragraph per card."""
    cards = [
        f"Card {n}\nFront: {card.front.strip()}\nBack: {card.back.strip()}"
        for n, card in enumerate(block.cards, start=1)
        if card.front.strip() or card.back.strip()
    ]
    if not cards:
        return ""
    head = f"Flash cards: {len(cards)} card{'s' if len(cards) != 1 else ''}."
    return BLOCK_SEPARATOR.join([head, *cards])


def _test_text(block: TestBlock, with_answers: bool) -> str:
    """``Test: N questions.`` then one paragraph per question."""
    questions = [
        _question_text(n, question, with_answers)
        for n, question in enumerate(block.questions, start=1)
        if question.prompt.strip()
    ]
    if not questions:
        return ""
    count = len(questions)
    head = f"Test: {count} question{'s' if count != 1 else ''}."
    return BLOCK_SEPARATOR.join([head, *questions])


def _question_text(number: int, question: Question, with_answers: bool) -> str:
    """One question: the prompt, what the student sees, then (optionally) the key."""
    kind = _TYPE_NAMES.get(question.type, question.type)
    prompt = _one_line(question.prompt)
    if question.type == "blanks":
        prompt = _BLANK.sub("____", prompt)
    lines = [f"Question {number} ({kind}): {prompt}", *_shown(question)]
    if with_answers:
        lines.extend(_answer_lines(question))
        if question.explanation and question.explanation.strip():
            lines.append(f"Explanation: {_one_line(question.explanation)}")
    return "\n".join(lines)


def _lettered(texts: Iterable[str]) -> str:
    return "; ".join(
        f"{_LETTERS[i % len(_LETTERS)]}) {_one_line(text)}"
        for i, text in enumerate(texts)
    )


def _shown(question: Question) -> list[str]:
    """What a student sees before answering (never the correctness)."""
    options = question.options or []
    if question.type in ("single", "multiple") and options:
        return [f"Options: {_lettered(o.text for o in options)}"]
    if question.type == "sorting" and options:
        items = sorted((_one_line(o.text) for o in options), key=str.casefold)
        return [f"Items (in random order): {'; '.join(items)}"]
    if question.type == "matching" and question.pairs:
        lefts = [_one_line(p.left) for p in question.pairs]
        rights = sorted((_one_line(p.right) for p in question.pairs), key=str.casefold)
        return [
            f"Left: {'; '.join(lefts)}",
            f"Right (in random order): {'; '.join(rights)}",
        ]
    if question.type == "table" and question.table is not None:
        return [
            f"Rows: {'; '.join(map(_one_line, question.table.rows))}",
            f"Columns: {'; '.join(map(_one_line, question.table.columns))}",
        ]
    if question.type == "random_number" and question.random is not None:
        names = ", ".join(v.name for v in question.random.variables)
        return [f"Variables: {names}"] if names else []
    if question.type == "code" and question.code is not None:
        return [f"Language: {question.code.language}"]
    return []


def _answer_lines(question: Question) -> list[str]:
    """The correct answer of a question, for the authors of the course."""
    if question.type in ("single", "multiple", "text", "number", "sorting"):
        return _simple_key(question)
    return _structured_key(question)


def _simple_key(question: Question) -> list[str]:
    """The key of a choice, text, number or sorting question."""
    options = question.options or []
    answer = question.answer
    if question.type in ("single", "multiple"):
        correct = [
            f"{_LETTERS[i % len(_LETTERS)]}) {_one_line(o.text)}"
            for i, o in enumerate(options)
            if o.correct
        ]
        return [f"Correct answer: {'; '.join(correct)}"] if correct else []
    if question.type == "text" and answer is not None:
        accepted = [_one_line(a) for a in answer.accepted or []]
        if answer.regex:
            accepted.append(f"matches /{answer.regex}/")
        return [f"Accepted answers: {'; '.join(accepted)}"] if accepted else []
    if question.type == "number" and answer is not None and answer.value is not None:
        tolerance = f" (±{answer.tolerance:g})" if answer.tolerance else ""
        return [f"Correct answer: {answer.value:g}{tolerance}"]
    if question.type == "sorting" and options:
        return [f"Correct order: {'; '.join(_one_line(o.text) for o in options)}"]
    return []


def _structured_key(question: Question) -> list[str]:
    """The key of a matching, table, blanks, random, formula or code question."""
    if question.type == "matching" and question.pairs:
        pairs = "; ".join(
            f"{_one_line(p.left)} — {_one_line(p.right)}" for p in question.pairs
        )
        return [f"Correct pairs: {pairs}"]
    if question.type == "table" and question.table is not None:
        table = question.table
        cells = [
            f"{_one_line(table.rows[r])} × {_one_line(table.columns[c])}"
            for r, line in enumerate(table.correct)
            for c, marked in enumerate(line)
            if marked and r < len(table.rows) and c < len(table.columns)
        ]
        return [f"Marked cells: {'; '.join(cells)}"] if cells else []
    if question.type == "blanks" and question.blanks:
        filled = "; ".join(
            f"{n}: {', '.join(b.accepted) or (f'/{b.regex}/' if b.regex else '?')}"
            for n, b in enumerate(question.blanks, start=1)
        )
        return [f"Blanks: {filled}"]
    if question.type == "random_number" and question.random is not None:
        return [f"Answer formula: {question.random.formula}"]
    if question.type == "formula" and question.formula is not None:
        return [f"Expected expression: {question.formula.expression}"]
    if question.type == "code" and question.code is not None:
        outputs = question.code.expected_outputs
        return [f"Expected output: {' | '.join(outputs)}"] if outputs else []
    return []


@dataclass(frozen=True, slots=True)
class MaterialRefs:
    """What a step points at besides its own text."""

    videos: tuple[VideoBlock, ...]
    files: tuple[UUID, ...]
    library_items: tuple[UUID, ...]


def material_refs(content: StepContent) -> MaterialRefs:
    """Videos, attached files (not video uploads) and linked library items of a step."""
    videos = tuple(b for b in content.blocks if isinstance(b, VideoBlock))
    text = json.dumps(content.model_dump(mode="json"), ensure_ascii=False)
    files = tuple(dict.fromkeys(UUID(m) for m in FILE_REFERENCE.findall(text)))
    library = tuple(dict.fromkeys(UUID(m) for m in LIBRARY_REFERENCE.findall(text)))
    return MaterialRefs(videos=videos, files=files, library_items=library)


def video_text(block: VideoBlock, step_title: str) -> str:
    """The text of a video: its caption (or the step title) and where to watch it.

    No transcript store exists yet; when it does, the transcript goes here.
    """
    title = block.caption.strip() or step_title.strip() or "Video"
    where = block.url.strip() if block.source == "link" else "uploaded video"
    return f"Video: {title}\n{where}".strip()
