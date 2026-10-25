"""The plain-text snippet of a search hit: about 200 characters around the first match.

No markup: the web finds and marks the words itself. Citation chips of saved answers
(`⟦1⟧`, `⟦w1,3⟧`) and line breaks are removed first.
"""

import re
from typing import Final

from app.modules.notebooks.domain.stop_words import STOP_WORDS

SEARCH_SNIPPET_CHARS: Final = 200
_LEAD: Final = 60  # characters shown before the first match
_MIN_WORD = 3
_MIN_STEM = 5  # as in the lexical query: shorter words are matched whole
_STEM_CUT = 3
_ELLIPSIS: Final = "…"

_CHIP = r"⟦w?\d+(?:\s*,\s*w?\d+)*⟧"
_MARKER_BEFORE_PUNCTUATION = re.compile(rf"\s*{_CHIP}(?=[.,;:!?)])")
_MARKER = re.compile(rf"\s*{_CHIP}\s*")
_APOSTROPHES = "ʻʼ’‘`´"
_WORD = re.compile(rf"[^\W_]+(?:['{_APOSTROPHES}][^\W_]+)*")
_FOLD_APOSTROPHES = str.maketrans(dict.fromkeys(_APOSTROPHES, "'"))


def _fold(text: str) -> str:
    """Lower-case text with one kind of apostrophe; the length does not change."""
    folded = text.translate(_FOLD_APOSTROPHES)
    return "".join(c if len(low := c.lower()) != 1 else low for c in folded)


def _stem(word: str) -> str:
    """The start of a word that its other endings share (the search stems words)."""
    if len(word) < _MIN_STEM:
        return word
    keep = len(word) - _STEM_CUT
    if word.isascii():  # Uzbek (Latin) endings chain, so cut to about half
        keep = min(keep, len(word) // 2 + 1)
    return word[: max(_MIN_STEM, keep)]


def _stems(query: str) -> list[str]:
    """Stems of the content words of the query."""
    stems: list[str] = []
    for match in _WORD.finditer(_fold(query)):
        word = match.group()
        letters = word.replace("'", "")
        if len(letters) >= _MIN_WORD and letters not in STOP_WORDS:
            stems.append(_stem(word))
    return stems


def _first_match(text: str, stems: list[str]) -> int:
    """Index of the earliest stem in the text, 0 when none is found."""
    folded = _fold(text)
    found = [at for stem in stems if (at := folded.find(stem)) != -1]
    return min(found, default=0)


def _window(text: str, at: int, width: int) -> tuple[int, int]:
    """Start and end of `width` characters around `at`, cut between words."""
    start = max(0, at - _LEAD)
    end = min(len(text), start + width)
    start = max(0, end - width)
    if start > 0 and text[start - 1] != " ":
        gap = text.find(" ", start, at)
        start = gap + 1 if gap != -1 else start
    if end < len(text) and text[end] != " ":
        gap = text.rfind(" ", at, end)
        end = gap if gap != -1 else end
    return start, end


def make_snippet(text: str, query: str, width: int = SEARCH_SNIPPET_CHARS) -> str:
    """Return one line of about `width` characters around the first word of the query.

    Args:
        text: The passage text.
        query: What was searched; its content words (with other endings) are looked
            for. A passage found by meaning has none, so its snippet is its start.
        width: The most characters of text in the snippet (ellipses come on top).
    """
    bare = _MARKER.sub(" ", _MARKER_BEFORE_PUNCTUATION.sub("", text))
    flat = " ".join(bare.split())
    if len(flat) <= width:
        return flat
    at = _first_match(flat, _stems(query))
    start, end = _window(flat, at, width)
    cut = flat[start:end].strip()
    return (
        f"{_ELLIPSIS if start > 0 else ''}{cut}{_ELLIPSIS if end < len(flat) else ''}"
    )
