"""Database-first web search: is what the platform holds enough for the question?

Topical density of a passage = on-topic tokens / all tokens, so a page with 100 tokens
about maths inside 10,000 other tokens (density 0.01) is not a good source. Coverage =
the share of the query terms found in dense passages.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass

from app.shared.contracts.web_search import PlatformPassage

_WORD = re.compile(r"\w+", re.UNICODE)
STEM = 5
MIN_TERM = 3
STOP = frozenset(
    "the and for with what how why who are was this that from into about "
    "что как это для при или его все так уже где когда почему какой "
    "uchun bilan qanday nima".split()
)


def stem(token: str) -> str:
    """A crude prefix stem that matches word endings in ru, uz and en."""
    return token[:STEM]


def tokens(text: str) -> list[str]:
    """Lower-cased word tokens."""
    return _WORD.findall(text.lower())


def query_terms(query: str) -> set[str]:
    """The stems of the meaningful words of a question."""
    return {stem(t) for t in tokens(query) if len(t) >= MIN_TERM and t not in STOP}


def density(text: str, terms: set[str]) -> float:
    """On-topic tokens / all tokens of the text (0 for an empty text)."""
    words = tokens(text)
    if not words or not terms:
        return 0.0
    return sum(1 for w in words if stem(w) in terms) / len(words)


def terms_in(text: str, terms: set[str]) -> set[str]:
    """The query terms that occur in the text."""
    return {stem(w) for w in tokens(text)} & terms


def coverage(dense: Sequence[PlatformPassage], terms: set[str]) -> float:
    """Share of the query terms covered by the dense passages."""
    covered: set[str] = set()
    for passage in dense:
        covered |= terms_in(passage.text, terms)
    return len(covered) / max(1, len(terms))


@dataclass(frozen=True, slots=True)
class Verdict:
    """The dense passages and whether they are enough to skip the web."""

    dense: tuple[PlatformPassage, ...]
    coverage: float
    sufficient: bool


def judge(
    passages: Sequence[PlatformPassage],
    query: str,
    *,
    min_density: float,
    min_coverage: float,
    min_passages: int,
) -> Verdict:
    """Keep the dense passages and decide whether the database is enough."""
    terms = query_terms(query)
    dense = tuple(p for p in passages if density(p.text, terms) >= min_density)
    cov = coverage(dense, terms)
    ok = bool(terms) and cov >= min_coverage and len(dense) >= min_passages
    return Verdict(dense, cov, ok)
