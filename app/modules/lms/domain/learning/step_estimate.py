"""What a step is about and how long it takes, read from its rendered blocks."""

import math
from collections.abc import Iterable, Mapping
from typing import Any, Final

WORDS_PER_MINUTE: Final = 200
SECONDS_PER_QUESTION: Final = 60
SECONDS_PER_CARD: Final = 15


def step_kind(blocks: Iterable[Mapping[str, Any]]) -> str | None:
    """Return the type of the first block of the step (None when it is empty)."""
    for block in blocks:
        return str(block.get("type") or "") or None
    return None


def _seconds(block: Mapping[str, Any]) -> float:
    """Return the working time one rendered block asks for, in seconds."""
    kind = block.get("type")
    if kind == "text":
        return len(str(block.get("markdown") or "").split()) * 60 / WORDS_PER_MINUTE
    if kind == "test":
        rules = block.get("rules") or {}
        limit = rules.get("time_limit_sec")
        if limit:
            return float(limit)
        return float(rules.get("questions") or 0) * SECONDS_PER_QUESTION
    if kind == "flashcards":
        return float(block.get("cards_count") or 0) * SECONDS_PER_CARD
    if kind == "exam":
        return float(
            sum(
                module.get("time_limit_sec") or 0
                for section in block.get("sections") or []
                for module in section.get("modules") or []
            )
        )
    return 0.0


def estimated_minutes(blocks: Iterable[Mapping[str, Any]]) -> int | None:
    """Return the minutes of reading, testing and cards (at least 1; None if empty)."""
    items = list(blocks)
    if not items:
        return None
    return max(1, math.ceil(sum(_seconds(block) for block in items) / 60))
