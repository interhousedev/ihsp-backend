"""Text normalisation that runs before chunking (§ 3.2.2).

The normaliser keeps a list of input offsets (page starts, unit starts) in step with
every rewrite, so the chunker can still cut on the same page boundaries.
"""

import re
import unicodedata
from bisect import bisect_left
from collections.abc import Callable, Sequence
from dataclasses import dataclass

_Replacement = str | Callable[[re.Match[str]], str | None]

# Line breaks that are not "\n": CR, CRLF, vertical tab, form feed, NEL, LS, PS.
_LINE_BREAKS = re.compile(r"\r\n?|[\x0b\x0c\x85  ]")
# No-break and other exotic spaces become a plain space.
_SPACES = re.compile(r"[\xa0  -   　]")
# Control characters (except "\n" and "\t"), NUL, zero-width characters, BOM.
_INVISIBLE = re.compile(r"[\x00-\x08\x0e-\x1f\x7f-\x9f​-‏⁠﻿]+")
# The lookbehind keeps a long run of spaces linear.
_TRAILING_SPACES = re.compile(r"(?<![ \t])[ \t]+(?=\n|\Z)")
# `letter` + hyphen (or soft hyphen) + line break + `letter`; lower case is checked.
_HYPHENATION = re.compile(r"(?<=[^\W\d_])[-\xad‐]\n(?=[^\W\d_])")
_SOFT_HYPHEN = re.compile("\xad")
# A soft hyphen is only a hint at a line end; everywhere else it is invisible, and
# so is one right after a hyphen ("word-\xad\nword" is the same as "word-\nword").
_INNER_SOFT_HYPHEN = re.compile("\xad(?!\n)|(?<=[-\u2010])\xad")
_BLANK_LINES = re.compile(r"\n{3,}")


@dataclass(frozen=True, slots=True)
class NormalizedText:
    """Normalised text and the input offsets mapped into it."""

    text: str
    marks: tuple[int, ...]


def _join_hyphenated(match: re.Match[str]) -> str | None:
    """Join a hyphenated word only when a lower-case letter follows the break."""
    return "" if match.string[match.end()].islower() else None


_STAGES: tuple[tuple[re.Pattern[str], _Replacement], ...] = (
    (_LINE_BREAKS, "\n"),
    (_SPACES, " "),
    (_INVISIBLE, ""),
    (_INNER_SOFT_HYPHEN, ""),
    (_TRAILING_SPACES, ""),
    (_HYPHENATION, _join_hyphenated),
    (_SOFT_HYPHEN, ""),
    (_TRAILING_SPACES, ""),  # a removed soft hyphen can leave trailing spaces
    (_BLANK_LINES, "\n\n"),
)


def _map_marks(
    marks: list[int],
    starts: list[int],
    ends: list[int],
    out_starts: list[int],
    out_lengths: list[int],
) -> list[int]:
    """Move offsets through a list of non-overlapping replacements."""
    mapped: list[int] = []
    for mark in marks:
        i = bisect_left(starts, mark) - 1  # the last replacement starting before
        if i < 0:
            mapped.append(mark)
        elif mark >= ends[i]:
            mapped.append(out_starts[i] + out_lengths[i] + mark - ends[i])
        else:  # inside a replaced region
            mapped.append(out_starts[i] + min(mark - starts[i], out_lengths[i]))
    return mapped


def _rewrite(
    text: str, marks: list[int], pattern: re.Pattern[str], repl: _Replacement
) -> tuple[str, list[int]]:
    """Apply one regex rewrite and carry the marks along."""
    pieces: list[str] = []
    starts: list[int] = []
    ends: list[int] = []
    out_starts: list[int] = []
    out_lengths: list[int] = []
    pos = 0
    out_len = 0
    for match in pattern.finditer(text):
        new = repl(match) if callable(repl) else repl
        if new is None:
            continue
        start, end = match.span()
        pieces.append(text[pos:start])
        out_len += start - pos
        starts.append(start)
        ends.append(end)
        out_starts.append(out_len)
        out_lengths.append(len(new))
        pieces.append(new)
        out_len += len(new)
        pos = end
    if not starts:
        return text, marks
    pieces.append(text[pos:])
    return "".join(pieces), _map_marks(marks, starts, ends, out_starts, out_lengths)


def _to_nfc(text: str, marks: list[int]) -> tuple[str, list[int]]:
    """Normalise to NFC segment by segment between the marks."""
    if unicodedata.is_normalized("NFC", text):
        return text, marks
    cuts = sorted({0, len(text), *marks})
    pieces: list[str] = []
    offsets: dict[int, int] = {}
    out_len = 0
    for begin, end in zip(cuts, cuts[1:], strict=False):
        offsets[begin] = out_len
        piece = unicodedata.normalize("NFC", text[begin:end])
        pieces.append(piece)
        out_len += len(piece)
    offsets[cuts[-1]] = out_len
    return "".join(pieces), [offsets[mark] for mark in marks]


def normalize_text(text: str, marks: Sequence[int] = ()) -> NormalizedText:
    """Normalise extracted text and map input offsets into the result.

    Applies NFC, turns every line break into a newline, replaces exotic spaces,
    removes control and zero-width characters, strips trailing spaces of each line,
    joins words hyphenated across lines (a letter, a hyphen, a line break and a
    lower-case letter) and collapses three or more newlines into one blank line.

    Args:
        text: The raw text.
        marks: Character offsets in `text` (page starts, unit starts).

    Returns:
        The text and the marks mapped to offsets in it: monotonic for monotonic input
        and clamped to the length of the result.
    """
    current = [min(max(mark, 0), len(text)) for mark in marks]
    out, current = _to_nfc(text, current)
    for pattern, repl in _STAGES:
        out, current = _rewrite(out, current, pattern, repl)
    return NormalizedText(out, tuple(min(mark, len(out)) for mark in current))
