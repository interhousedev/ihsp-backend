"""Folded text search over an owner's essay fields (pure, in memory)."""

import unicodedata
from dataclasses import dataclass
from typing import Final
from uuid import UUID

from app.modules.admission.domain.essays import Essay

MIN_QUERY: Final = 2
MAX_QUERY: Final = 80
SNIPPET: Final = 120

_APOSTROPHES: Final = frozenset("ʼʻ'’`‘")
_FIELDS: Final = ("title", "prompt", "body", "notes")


def _fold_char(char: str) -> str:
    if char in _APOSTROPHES:
        return ""
    text = unicodedata.normalize("NFKD", char).lower()
    text = "".join(c for c in text if not unicodedata.combining(c))
    return text.replace("ё", "е")


def fold(text: str) -> str:
    """Lower-case, strip diacritics, ё→е and every apostrophe variant."""
    return "".join(_fold_char(c) for c in text)


def _folded_with_map(text: str) -> tuple[str, list[int]]:
    """Folded text and, per folded character, the index in the original."""
    out: list[str] = []
    index: list[int] = []
    for i, char in enumerate(text):
        piece = _fold_char(char)
        out.append(piece)
        index.extend([i] * len(piece))
    return "".join(out), index


@dataclass(frozen=True, slots=True)
class EssayHit:
    """The first match of a query in one essay."""

    essay_id: UUID
    title: str
    field: str
    snippet: str
    match_start: int
    match_end: int


def _snippet(text: str, start: int, end: int) -> tuple[str, int, int]:
    """About SNIPPET characters of context around the span (text is collapsed)."""
    room = max(SNIPPET - (end - start), 0)
    lo = max(start - room // 2, 0)
    hi = min(lo + max(SNIPPET, end - lo), len(text))
    lo = max(min(lo, start), 0)
    prefix = "…" if lo > 0 else ""
    suffix = "…" if hi < len(text) else ""
    return (
        prefix + text[lo:hi] + suffix,
        len(prefix) + start - lo,
        len(prefix) + end - lo,
    )


def find(query: str, essay: Essay) -> EssayHit | None:
    """First match of the folded query in the title, prompt, body or notes."""
    needle = fold(query).strip()
    if len(needle) < MIN_QUERY:
        return None
    prompts = " ".join([essay.prompt_text, *(t.prompt for t in essay.targets)])
    fields = {
        "title": essay.title,
        "prompt": prompts.strip(),
        "body": essay.body,
        "notes": essay.notes,
    }
    for name in _FIELDS:
        text = " ".join(fields[name].split())
        folded, index = _folded_with_map(text)
        at = folded.find(needle)
        if at < 0:
            continue
        start = index[at]
        end = index[at + len(needle) - 1] + 1
        snippet, lo, hi = _snippet(text, start, end)
        return EssayHit(essay.id, essay.title, name, snippet, lo, hi)
    return None
