"""In-item search: folding, finding a query in a page, and the snippet around it."""

import re
import unicodedata
from dataclasses import dataclass

from app.shared.text import search_normalize

MIN_QUERY_CHARS = 2
SNIPPET_CONTEXT = 60
_WORD = re.compile(r"\S+")


@dataclass(frozen=True, slots=True)
class Match:
    """A hit on a page: the span of the page text it covers (whole words)."""

    start: int
    end: int


@dataclass(frozen=True, slots=True)
class Snippet:
    """The text around a hit, whitespace collapsed."""

    pre: str
    match: str
    post: str


def fold_text(text: str) -> str:
    """Lower-case, no diacritics (й to и, ё to е, é to e), whitespace collapsed."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    bare = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return " ".join(bare.split())


def fold_query(query: str, language: str) -> str:
    """The needle for the stored folded text: script-normalised, then folded."""
    return fold_text(search_normalize(query, language))


def _fold_word(word: str, language: str) -> str:
    return fold_text(search_normalize(word, language)).replace(" ", "")


def locate(text: str, query: str, language: str, *, limit: int = 50) -> list[Match]:
    """Find the query (several words in a row) in a page, as spans of ``text``.

    Matching ignores case, diacritics and, for Uzbek, the script. A hit may sit inside
    a word; the span always covers whole words so a box can be drawn for them.
    """
    needle = fold_query(query, language)
    if not needle:
        return []
    spans = [(m.start(), m.end()) for m in _WORD.finditer(text)]
    words = [_fold_word(text[s:e], language) for s, e in spans]
    starts: list[int] = []
    pieces: list[str] = []
    position = 0
    for word in words:
        starts.append(position)
        pieces.append(word)
        position += len(word) + 1
    haystack = " ".join(pieces)
    matches: list[Match] = []
    seen_last = -1
    at = haystack.find(needle)
    while at >= 0 and len(matches) < limit:
        first = _word_at(starts, at)
        last = _word_at(starts, at + len(needle) - 1)
        if first > seen_last:
            matches.append(Match(spans[first][0], spans[last][1]))
            seen_last = last
        at = haystack.find(needle, at + 1)
    return matches


def _word_at(starts: list[int], offset: int) -> int:
    low, high = 0, len(starts) - 1
    while low < high:
        mid = (low + high + 1) // 2
        if starts[mid] <= offset:
            low = mid
        else:
            high = mid - 1
    return low


def snippet(
    text: str, start: int, end: int, *, context: int = SNIPPET_CONTEXT
) -> Snippet:
    """The hit with about ``context`` characters on each side."""
    pre = " ".join(text[max(0, start - context) : start].split())
    post = " ".join(text[end : end + context].split())
    return Snippet(
        pre=("…" if start > context else "") + pre.lstrip() if pre else "",
        match=" ".join(text[start:end].split()),
        post=post + ("…" if end + context < len(text) else "") if post else "",
    )
