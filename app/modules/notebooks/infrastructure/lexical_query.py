"""Turns a question into the `tsquery` texts of the lexical passage search.

PostgreSQL tokenises text itself, so the query side only has to (1) pick the content
words of the question and (2) write them as an OR query that is safe to hand to
`to_tsquery`. Two texts are produced, one for the `russian` configuration (stemming:
"фотосинтезе" finds "фотосинтез") and one for `simple` with prefix terms
("fotosintezda" finds "fotosintez" and "fotosintezlarning": Uzbek endings).

The Postgres parser treats the Uzbek letters ʻ (U+02BB) and ʼ (U+02BC) as letters and
splits words at ' ’ ‘ ` ´, so a query word with an apostrophe is looked up in each of
those spellings.
"""

import re
from dataclasses import dataclass

from app.modules.notebooks.domain.stop_words import STOP_WORDS

MAX_TERMS = 12
MIN_TERM_LENGTH = 3
MIN_PREFIX_LENGTH = 5  # shorter words are matched exactly only
PREFIX_CUT = 3  # a prefix term drops up to this many trailing characters

# Letters in the Postgres text parser (kept inside a word).
TURNED_COMMA = "ʻ"  # ʻ  oʻ gʻ
APOSTROPHE_LETTER = "ʼ"  # ʼ
# Characters that are written instead of them but split a word in the parser.
SEPARATING_APOSTROPHES = "'’‘`´"

_WORD = re.compile(
    rf"[^\W_]+(?:[{TURNED_COMMA}{APOSTROPHE_LETTER}{SEPARATING_APOSTROPHES}][^\W_]+)*"
)
_LATIN = re.compile(f"[a-z0-9{TURNED_COMMA}{APOSTROPHE_LETTER}]+")
_APOSTROPHES = re.compile(
    f"[{TURNED_COMMA}{APOSTROPHE_LETTER}{SEPARATING_APOSTROPHES}]"
)


@dataclass(frozen=True, slots=True)
class LexicalQuery:
    """OR queries for `to_tsquery('russian', ...)` and `to_tsquery('simple', ...)`."""

    russian: str
    simple: str


def _letters(word: str) -> int:
    """Number of letters and digits of a word (apostrophes do not count)."""
    return len(_APOSTROPHES.sub("", word))


def _spellings(word: str) -> list[str]:
    """The forms of a word that the parser can have produced for the text.

    A word without an apostrophe has one form. "o'zbek" (any of the apostrophes) is
    searched as "oʻzbek", "oʼzbek" (kept whole by the parser) and as its parts
    "zbek" (the parser split it at the apostrophe).
    """
    if _APOSTROPHES.search(word) is None:
        return [word]
    forms = [
        _APOSTROPHES.sub(TURNED_COMMA, word),
        _APOSTROPHES.sub(APOSTROPHE_LETTER, word),
    ]
    forms += [part for part in _APOSTROPHES.split(word) if len(part) >= MIN_TERM_LENGTH]
    return list(dict.fromkeys(forms))


def _prefix(term: str) -> str | None:
    """The stem that finds other endings of the word, None for short words.

    Latin-script (Uzbek) words are agglutinative, with chains such as -lar-ning, so
    their stem is cut to about half the word; others lose only the last 3 letters
    (the `russian` configuration stems Russian words itself).
    """
    if len(term) < MIN_PREFIX_LENGTH:
        return None
    keep = len(term) - PREFIX_CUT
    if _LATIN.fullmatch(term):
        keep = min(keep, len(term) // 2 + 1)
    return term[: max(MIN_PREFIX_LENGTH, keep)]


def content_words(text: str) -> list[str]:
    """Lower-case content words of a question: 3+ letters, no stop words, unique.

    At most `MAX_TERMS`, in the order they appear.
    """
    words: list[str] = []
    for match in _WORD.finditer(text.lower()):
        word = match.group()
        plain = _APOSTROPHES.sub("", word)
        if _letters(word) < MIN_TERM_LENGTH or plain in STOP_WORDS:
            continue
        if word not in words:
            words.append(word)
        if len(words) == MAX_TERMS:
            break
    return words


def build_lexical_query(text: str) -> LexicalQuery | None:
    """The `tsquery` texts for a question, None when it has no content word."""
    words = content_words(text)
    if not words:
        return None
    exact = list(dict.fromkeys(form for word in words for form in _spellings(word)))
    prefixes = [f"{stem}:*" for term in exact if (stem := _prefix(term)) is not None]
    return LexicalQuery(
        russian=" | ".join(exact),
        simple=" | ".join(list(dict.fromkeys([*exact, *prefixes]))),
    )
