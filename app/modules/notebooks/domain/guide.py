"""Source guide and notebook summary: output models, schemas and soft parsing.

§ 3.2.5 (source guide) and § 3.2.6 (notebook title, emoji, summary). The model's JSON
is repaired softly (lists are cut to their maximum, empty strings dropped); only a
document without any summary text is an `OutputInvalidError`.
"""

import unicodedata
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

from app.modules.notebooks.domain.artifacts.strict import to_strict_schema
from app.modules.notebooks.domain.entities import NotebookSummary, SourceGuide
from app.modules.notebooks.domain.errors import OutputInvalidError
from app.modules.notebooks.domain.limits import (
    DEFAULT_NOTEBOOK_TITLE,
    NOTEBOOK_TITLE_MAX_CHARS,
)

from pydantic import BaseModel, Field

GUIDE_SCHEMA_NAME: Final = "nb_guide"
SUMMARY_SCHEMA_NAME: Final = "nb_summary"

GUIDE_TOPICS_MAX: Final = 8
GUIDE_QUESTIONS_MAX: Final = 3
SUMMARY_TOPICS_MAX: Final = 10
SUGGESTED_QUESTIONS_MAX: Final = 6
GUIDE_SUMMARY_MAX_CHARS: Final = 2000
SUMMARY_MAX_CHARS: Final = 3000
TOPIC_MAX_CHARS: Final = 80
QUESTION_MAX_CHARS: Final = 300


class GuideOutput(BaseModel):
    """The JSON of a source guide (``nb_guide``)."""

    summary: str = Field(description="60 to 120 words, plain Markdown, no citations")
    key_topics: list[str] = Field(
        description="5 to 8 main concepts of 2 to 5 words, in the order they appear"
    )
    questions: list[str] = Field(
        description="3 specific questions a student could ask, answerable from the text"
    )


class SummaryOutput(BaseModel):
    """The JSON of a notebook summary (``nb_summary``)."""

    title: str = Field(description="2 to 6 words")
    emoji: str = Field(description="exactly one emoji")
    summary: str = Field(
        description="80 to 160 words, Markdown with **bold** key phrases, no citations"
    )
    key_topics: list[str] = Field(description="6 to 10 main concepts")
    suggested_questions: list[str] = Field(
        description="4 to 6 questions the sources can answer"
    )


@dataclass(frozen=True, slots=True)
class ParsedSummary:
    """A validated notebook summary with the title and emoji the model proposed."""

    title: str
    emoji: str | None
    summary: NotebookSummary


def guide_schema() -> dict[str, Any]:
    """Strict JSON schema of the source guide."""
    return to_strict_schema(GuideOutput)


def summary_schema() -> dict[str, Any]:
    """Strict JSON schema of the notebook summary."""
    return to_strict_schema(SummaryOutput)


# - - - soft parsing - - -


def _clip(text: str, limit: int) -> str:
    """Cut to ``limit`` characters; an ellipsis marks a cut."""
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _text(value: Any, limit: int) -> str:
    """A string field: trimmed and cut; anything that is not a string is empty."""
    return _clip(value.strip(), limit) if isinstance(value, str) else ""


def _line(value: Any, limit: int) -> str:
    """A one-line string field: whitespace collapsed, then cut."""
    return _clip(" ".join(value.split()), limit) if isinstance(value, str) else ""


def _items(value: Any, maximum: int, item_limit: int) -> list[str]:
    """A list of short strings: empty and repeated items dropped, cut to ``maximum``."""
    if not isinstance(value, list):
        return []
    seen: set[str] = set()
    items: list[str] = []
    for raw in value:
        item = _line(raw, item_limit)
        if item and item.casefold() not in seen:
            seen.add(item.casefold())
            items.append(item)
    return items[:maximum]


def _require_document(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise OutputInvalidError(["the answer must be one JSON object"])
    return data


def parse_guide(data: dict[str, Any]) -> SourceGuide:
    """Validate and repair a source guide.

    Raises:
        OutputInvalidError: The document has no summary text.
    """
    document = _require_document(data)
    summary = _text(document.get("summary"), GUIDE_SUMMARY_MAX_CHARS)
    if not summary:
        raise OutputInvalidError(["summary is missing or empty"])
    return SourceGuide(
        summary=summary,
        key_topics=_items(
            document.get("key_topics"), GUIDE_TOPICS_MAX, TOPIC_MAX_CHARS
        ),
        questions=_items(
            document.get("questions"), GUIDE_QUESTIONS_MAX, QUESTION_MAX_CHARS
        ),
    )


def parse_summary(data: dict[str, Any], now: datetime) -> ParsedSummary:
    """Validate and repair a notebook summary.

    A missing title falls back to the first key topic, then to the default title.

    Raises:
        OutputInvalidError: The document has no summary text.
    """
    document = _require_document(data)
    summary = _text(document.get("summary"), SUMMARY_MAX_CHARS)
    if not summary:
        raise OutputInvalidError(["summary is missing or empty"])
    topics = _items(document.get("key_topics"), SUMMARY_TOPICS_MAX, TOPIC_MAX_CHARS)
    title = _line(document.get("title"), NOTEBOOK_TITLE_MAX_CHARS)
    emoji = document.get("emoji")
    return ParsedSummary(
        title=title or (topics[0] if topics else DEFAULT_NOTEBOOK_TITLE),
        emoji=single_emoji(emoji) if isinstance(emoji, str) else None,
        summary=NotebookSummary(
            summary=summary,
            key_topics=topics,
            suggested_questions=_items(
                document.get("suggested_questions"),
                SUGGESTED_QUESTIONS_MAX,
                QUESTION_MAX_CHARS,
            ),
            generated_at=now,
        ),
    )


# - - - emoji - - -

_ZWJ: Final = "‍"
_VARIATION_SELECTOR: Final = "️"
_KEYCAP: Final = "⃣"
_KEYCAP_BASES: Final = frozenset("0123456789#*")
_ALWAYS_EMOJI: Final = frozenset({0x203C, 0x2049, 0x3030})


def _is_regional(ch: str) -> bool:
    return 0x1F1E6 <= ord(ch) <= 0x1F1FF


def _is_modifier(ch: str) -> bool:
    """Variation selector, skin tone or tag character (they extend an emoji)."""
    code = ord(ch)
    return (
        ch == _VARIATION_SELECTOR
        or 0x1F3FB <= code <= 0x1F3FF
        or 0xE0020 <= code <= 0xE007F
    )


def _is_pictograph(ch: str) -> bool:
    code = ord(ch)
    if code in _ALWAYS_EMOJI:
        return True
    if 0x1F300 <= code <= 0x1FAFF:  # includes code points newer than this Unicode
        return True
    if code < 0x2000 or 0x2800 <= code <= 0x28FF:  # ASCII, Latin-1, Braille
        return False
    return unicodedata.category(ch) == "So"


def _unit_end(text: str, start: int) -> int | None:
    """End index of one emoji (flag, keycap or pictograph with modifiers)."""
    if start >= len(text):
        return None
    ch = text[start]
    if _is_regional(ch):
        pair = start + 1 < len(text) and _is_regional(text[start + 1])
        return start + 2 if pair else None
    if ch in _KEYCAP_BASES:
        rest = text[start + 1 :]
        offset = 1 if rest.startswith(_VARIATION_SELECTOR) else 0
        return start + 2 + offset if rest[offset : offset + 1] == _KEYCAP else None
    if not _is_pictograph(ch):
        return None
    end = start + 1
    while end < len(text) and _is_modifier(text[end]):
        end += 1
    return end


def single_emoji(value: str) -> str | None:
    """Return the first emoji grapheme of ``value`` (ZWJ sequences included) or None."""
    text = value.strip()
    end = _unit_end(text, 0)
    if end is None:
        return None
    while end < len(text) and text[end] == _ZWJ:
        joined = _unit_end(text, end + 1)
        if joined is None:
            break
        end = joined
    return text[:end]
