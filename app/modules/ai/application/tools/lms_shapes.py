"""How course steps look to the model and on approval cards.

The model sees a step's blocks numbered from 1, without the inner ids (it keeps a
block by its number). A step too large for one tool result is shortened in stages,
and a note tells the model how to read one block in full.
"""

import json
from typing import Any

from app.modules.ai.application.tools.lms_common import (
    draft_blocks,
    first_lines,
    step_title,
)
from app.modules.ai.domain.errors import ToolFailedError
from app.shared.i18n.core import I18nCore

FULL_CHARS = 10_000  # a step whose blocks fit in this is shown in full
TEXT_CUT = 1_500
COMPACT_TEXT_CUT = 400
ONE_BLOCK_TEXT = 10_000
COMPACT_CARDS = 10
PROMPT_CUT = 160
CARD_LINES = 30
QUESTION_LINES = 50
SHORTENED_NOTE = (
    "Some blocks are shortened. Read one in full with get_step_draft "
    '{"step_id": ..., "block": N}. In replace_step_content keep a block unchanged '
    'with {"type": "keep", "block": N} instead of copying it.'
)


def step_for_model(draft: dict[str, Any], block: int | None) -> dict[str, Any]:
    """Return a step draft for the model: one block in full, or all, shortened."""
    blocks = draft_blocks(draft)
    head = {
        "step_id": str(draft.get("step_id")),
        "title": step_title(draft),
        "lock_version": draft.get("lock_version"),
        "status": draft.get("status"),
        "updated_via": draft.get("updated_via"),
        "blocks_total": len(blocks),
    }
    if block is not None:
        if block > len(blocks):
            raise ToolFailedError(
                support_details=f"the step has {len(blocks)} blocks; block {block} "
                "does not exist"
            )
        one = model_block(block, blocks[block - 1], text_cut=ONE_BLOCK_TEXT)
        return {**head, "blocks": [one]}
    full = [model_block(n, b) for n, b in enumerate(blocks, start=1)]
    if _size(full) <= FULL_CHARS:
        return {**head, "blocks": full}
    shorter = [model_block(n, b, TEXT_CUT) for n, b in enumerate(blocks, start=1)]
    if _size(shorter) > FULL_CHARS:
        shorter = [
            model_block(n, b, COMPACT_TEXT_CUT, compact=True)
            for n, b in enumerate(blocks, start=1)
        ]
    return {**head, "blocks": shorter, "note": SHORTENED_NOTE}


def _size(blocks: list[dict[str, Any]]) -> int:
    return len(json.dumps(blocks, ensure_ascii=False))


def model_block(
    number: int,
    block: dict[str, Any],
    text_cut: int | None = None,
    *,
    compact: bool = False,
) -> dict[str, Any]:
    """Return one block without ids; long parts are cut and marked ``shortened``."""
    kind = str(block.get("type"))
    shown: dict[str, Any] = {"block": number, "type": kind}
    if kind == "text":
        markdown = str(block.get("markdown") or "")
        cut = markdown if text_cut is None else markdown[:text_cut]
        shown["markdown"] = cut
        if len(cut) < len(markdown):
            shown.update(shortened=True, chars=len(markdown))
    elif kind == "video":
        shown.update(url=block.get("url"), caption=block.get("caption") or "")
    elif kind == "test":
        shown.update(_test(block, compact))
    elif kind == "flashcards":
        shown.update(_cards(block, compact))
    return shown


def _test(block: dict[str, Any], compact: bool) -> dict[str, Any]:
    questions = [q for q in block.get("questions") or [] if isinstance(q, dict)]
    if compact:
        return {
            "questions_total": len(questions),
            "questions": [
                {"prompt": str(q.get("prompt", ""))[:PROMPT_CUT]} for q in questions
            ],
            "shortened": True,
        }
    return {
        "settings": block.get("config") or {},
        "questions": [_question(q) for q in questions],
    }


def _question(question: dict[str, Any]) -> dict[str, Any]:
    shown = {
        key: question[key]
        for key in ("type", "prompt", "points", "explanation", "answer")
        if question.get(key) is not None
    }
    for key in ("pairs", "table", "blanks", "random", "formula", "code"):
        if question.get(key):
            shown[key] = _without_ids(question[key])
    options = question.get("options")
    if isinstance(options, list):
        shown["options"] = [
            {"text": o.get("text"), "correct": bool(o.get("correct"))}
            | ({"pinned": True} if o.get("pinned") else {})
            for o in options
            if isinstance(o, dict)
        ]
    return shown


def _without_ids(value: Any) -> Any:  # noqa: ANN401 - any JSON value
    if isinstance(value, dict):
        return {k: _without_ids(v) for k, v in value.items() if k != "id"}
    if isinstance(value, list):
        return [_without_ids(v) for v in value]
    return value


def _cards(block: dict[str, Any], compact: bool) -> dict[str, Any]:
    cards = [
        {"front": c.get("front"), "back": c.get("back")}
        for c in block.get("cards") or []
        if isinstance(c, dict)
    ]
    if compact and len(cards) > COMPACT_CARDS:
        return {
            "cards_total": len(cards),
            "cards": cards[:COMPACT_CARDS],
            "shortened": True,
        }
    return {"cards": cards}


# - - - Approval card lines - - -


def _rich_answer(question: dict[str, Any]) -> str | None:
    """The answer of the richer question types; None for text, number and choice."""
    kind = question.get("type")
    options = question.get("options") or []
    if kind == "sorting":
        return " → ".join(str(o["text"]) for o in options)
    if kind == "matching":
        pairs = question.get("pairs") or []
        return "; ".join(f"{p['left']} = {p['right']}" for p in pairs)
    if kind == "blanks":
        found = (b.get("accepted") or [] for b in question.get("blanks") or [])
        return "; ".join(" / ".join(map(str, accepted)) for accepted in found)
    if kind == "formula":
        return str((question.get("formula") or {}).get("expression", ""))
    if kind == "random_number":
        return str((question.get("random") or {}).get("formula", ""))
    if kind in ("table", "code", "free"):
        return ""
    return None


def answer_text(question: dict[str, Any]) -> str:
    """Return the right answer of a built question for an approval card."""
    rich = _rich_answer(question)
    if rich is not None:
        return rich
    options = question.get("options")
    if isinstance(options, list):
        return "; ".join(str(o["text"]) for o in options if o.get("correct"))
    answer = question.get("answer") or {}
    if answer.get("value") is not None:
        tolerance = answer.get("tolerance") or 0
        return f"{answer['value']}" + (f" ± {tolerance}" if tolerance else "")
    accepted = answer.get("accepted") or []
    return " / ".join(map(str, accepted)) or f"/{answer.get('regex', '')}/"


def question_lines(i18n: I18nCore, locale: str, block: dict[str, Any]) -> list[str]:
    """Return one line per question of a built test block: prompt and answer."""
    return [
        i18n.t(
            locale,
            "ai-item-question",
            n=n,
            prompt=" ".join(str(q.get("prompt", "")).split())[:PROMPT_CUT],
            answer=answer_text(q),
        )
        for n, q in enumerate(block.get("questions") or [], start=1)
    ][:QUESTION_LINES]


def card_lines(block: dict[str, Any]) -> list[str]:
    """Return ``front → back`` lines of a built flash cards block."""
    lines = [
        f"{c.get('front', '')} → {c.get('back', '')}"[:PROMPT_CUT]
        for c in block.get("cards") or []
    ]
    if len(lines) > CARD_LINES:
        return [*lines[:CARD_LINES], "…"]
    return lines


def block_line(i18n: I18nCore, locale: str, block: dict[str, Any]) -> str:
    """Return one approval card line that sums up a built block."""
    kind = block.get("type")
    if kind == "text":
        lines = first_lines(str(block.get("markdown") or ""), lines=1, chars=120)
        preview = lines[0] if lines else ""
        return i18n.t(locale, "ai-item-text", preview=preview)
    if kind == "video":
        return str(block.get("url") or "")[:120]
    if kind == "test":
        count = len(block.get("questions") or [])
        return i18n.t(locale, "ai-item-test", count=count)
    count = len(block.get("cards") or [])
    return i18n.t(locale, "ai-item-cards", count=count)


def keep_line(i18n: I18nCore, locale: str, number: int, block: dict[str, Any]) -> str:
    """Return the card line of an existing block that a rewrite keeps."""
    return i18n.t(
        locale, "ai-item-keep", n=number, block=block_line(i18n, locale, block)
    )


def outline_lines(i18n: I18nCore, locale: str, rows: list[dict[str, Any]]) -> list[str]:
    """Return the card lines of an outline: each section and step, new or existing."""
    lines: list[str] = []
    for row in rows:
        lines.append(_outline_line(i18n, locale, "ai-item-section", row))
        lines.extend(
            _outline_line(i18n, locale, "ai-item-step", step)
            for step in row.get("steps") or []
        )
    return lines


def _outline_line(i18n: I18nCore, locale: str, key: str, row: dict[str, Any]) -> str:
    state_key = "ai-item-exists" if row.get("action") == "exists" else "ai-item-new"
    state = i18n.t(locale, state_key)
    return i18n.t(locale, key, title=row.get("title", ""), state=state)


def count_new(rows: list[dict[str, Any]]) -> tuple[int, int]:
    """Return how many sections and steps of a dry-run outline are new."""
    sections = sum(1 for row in rows if row.get("action") == "new")
    steps = sum(
        1
        for row in rows
        for step in row.get("steps") or []
        if step.get("action") == "new"
    )
    return sections, steps
