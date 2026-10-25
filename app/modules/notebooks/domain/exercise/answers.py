"""Answer rules of exercises: normalisation, word limits, grading, originality.

The web client grades the objective questions with the same rules (the quiz has no
server-side submission either); `grade_answer` is the reference implementation.
"""

import re
from collections.abc import Iterable, Sequence
from typing import Any, Final

_EDGE_PUNCT: Final = re.compile(
    r"^[\s\"'«»“”‘’.,;:!?()\[\]-]+|[\s\"'«»“”‘’.,;:!?()\[\]-]+$"
)
_SPACES: Final = re.compile(r"\s+")
_WORD: Final = re.compile(r"[\w'’-]+", re.UNICODE)
COPY_RUN_WORDS: Final = 12  # this many words in a row copied = verbatim copying


def normalize_answer(text: str) -> str:
    """Case-, whitespace- and edge-punctuation-insensitive form of an answer."""
    flat = _SPACES.sub(" ", text.casefold()).strip()
    return _EDGE_PUNCT.sub("", flat)


def word_count(text: str) -> int:
    """Words of a text (numbers count as words, as in IELTS)."""
    return len(_WORD.findall(text))


def within_limit(answer: str, word_limit: int) -> bool:
    """True when the answer respects the word limit (0 = no limit)."""
    return word_limit <= 0 or word_count(answer) <= word_limit


def text_matches(answer: str, accepted: Sequence[str], word_limit: int) -> bool:
    """A gap or short answer: within the limit and equal to one accepted answer."""
    key = normalize_answer(answer)
    if not key or not within_limit(answer, word_limit):
        return False
    return any(key == normalize_answer(item) for item in accepted)


def grade_answer(question: dict[str, Any], answer: Any) -> tuple[int, int]:
    """(points earned, points possible) of one stored question; essays are (0, 0)."""
    kind = question.get("type")
    if kind == "free_response":
        return 0, 0
    if kind == "matching":
        items = question.get("items") or []
        given = answer if isinstance(answer, dict) else {}
        earned = sum(1 for item in items if given.get(item["id"]) == item["answer"])
        return earned, len(items)
    if kind in ("gap_fill", "short_answer"):
        ok = isinstance(answer, str) and text_matches(
            answer, question.get("accepted") or [], int(question.get("word_limit") or 0)
        )
        return int(ok), 1
    chosen = answer if isinstance(answer, list) else [answer]
    return int(sorted(map(str, chosen)) == sorted(question.get("correct") or [])), 1


def _words(text: str) -> list[str]:
    return [word.casefold() for word in _WORD.findall(text)]


def copied_run(text: str, sources: Iterable[str], run: int = COPY_RUN_WORDS) -> bool:
    """True when `text` repeats `run` or more words in a row from one of `sources`."""
    words = _words(text)
    if len(words) < run:
        return False
    mine = {tuple(words[i : i + run]) for i in range(len(words) - run + 1)}
    for source in sources:
        theirs = _words(source)
        for i in range(len(theirs) - run + 1):
            if tuple(theirs[i : i + run]) in mine:
                return True
    return False


def in_text(answer: str, text: str) -> bool:
    """True when the answer's words appear in this order in the text."""
    needle = " ".join(_words(answer))
    return bool(needle) and f" {needle} " in f" {' '.join(_words(text))} "
