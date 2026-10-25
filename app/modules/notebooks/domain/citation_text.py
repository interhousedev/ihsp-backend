"""Text-level helpers of the citation protocol (§ 3.3.5): markers, code, line starts.

Everything here is a pure function of a string; `citations.py` holds the stateful part
(numbering and streaming).
"""

import re
from collections.abc import Callable, Iterable
from typing import Literal

CITATION_OPEN = "⟦"
CITATION_CLOSE = "⟧"
MAX_LABELS = 6  # per marker: [[S1:P1, ... ]] allows one plus five more
MAX_MARKER_CHARS = 200  # a longer `[[...` is not waited for

_LABEL = r"[Ss]\d+\s*:\s*[Pp]\d+"
MARKER = re.compile(rf"\[\[\s*{_LABEL}(?:\s*,\s*{_LABEL})*\s*\]\]")
_LABEL_PARTS = re.compile(r"[Ss](\d+)\s*:\s*[Pp](\d+)")
# What `[[...` may still become: only these characters can appear before `]]`.
_PARTIAL_MARKER = re.compile(r"\[\[[\sSsPp:,\d]*\]?")
_PARTIAL_START = re.compile(r"\[\[?[\sSsPp:,\d]*\]?")

_BULLET = r"(?:[-*+]|\d{1,9}[.)])[ \t]"
_BULLET_PREFIX = re.compile(r"(?:[-*+]|\d{1,9}[.)]?)?")
_LEADING_MARKERS = re.compile(rf"[ \t]*(?:{MARKER.pattern}[ \t]*)+")
_MOVABLE = re.compile(rf"([ \t]*)((?:{MARKER.pattern}[ \t]*)+)(?={_BULLET})")

FENCE_OPEN = re.compile(r" {0,3}(`{3,}|~{3,})")
FENCE_CLOSE = re.compile(r" {0,3}(`{3,}|~{3,})[ \t]*")
_TICKS = re.compile(r"`+")
_FOLLOWUPS_WORD = "<followups"
_TAIL_WORDS = (_FOLLOWUPS_WORD, "<action")  # what may start the hidden tail

Resolver = Callable[[Iterable[str]], list[int]]
StartState = Literal["normal", "move", "undecided"]


def marker_labels(marker: str) -> list[str]:
    """Return the labels of a marker text, normalised: ``[[ s1 : p2 ]]`` -> S1:P2."""
    return [
        f"S{source.lstrip('0') or '0'}:P{seq.lstrip('0') or '0'}"
        for source, seq in _LABEL_PARTS.findall(marker)
    ]


def format_numbers(numbers: Iterable[int]) -> str:
    """Return ``⟦1⟧`` or ``⟦1,2⟧`` (ascending)."""
    return (
        CITATION_OPEN + ",".join(str(n) for n in sorted(set(numbers))) + CITATION_CLOSE
    )


def code_spans(text: str, *, partial: bool) -> tuple[list[tuple[int, int]], int | None]:
    """Find inline code spans in one line.

    Args:
        text: The line.
        partial: True when more text may follow. A backtick run that touches the end
            may still grow, so it is not used to close a span.

    Returns:
        The matched spans ``(start, end)`` and the start of the first backtick run
        that has no partner yet (None when every run is resolved or literal).
    """
    runs = [(m.start(), m.end()) for m in _TICKS.finditer(text)]
    tail_start: int | None = None
    if partial and runs and runs[-1][1] == len(text):
        tail_start = runs.pop()[0]
    spans: list[tuple[int, int]] = []
    unresolved: int | None = None
    i = 0
    while i < len(runs):
        size = runs[i][1] - runs[i][0]
        j = next(
            (k for k in range(i + 1, len(runs)) if runs[k][1] - runs[k][0] == size),
            None,
        )
        if j is None:
            unresolved = runs[i][0] if unresolved is None else unresolved
            i += 1
        else:
            spans.append((runs[i][0], runs[j][1]))
            i = j + 1
    if partial and tail_start is not None:
        unresolved = tail_start if unresolved is None else min(unresolved, tail_start)
    return spans, unresolved if partial else None


def open_marker(text: str) -> int | None:
    """Return where an unfinished ``[[...`` marker starts at the end of `text`."""
    start = text.rfind("[[")
    if start < 0 or len(text) - start > MAX_MARKER_CHARS:
        return None
    return start if _PARTIAL_MARKER.fullmatch(text[start:]) else None


def followups_hold(text: str) -> int:
    """Return where a possible ``<followups`` or ``<action`` prefix starts (or len).

    Both tags open the tail of an answer, which is never shown.
    """
    for size in range(min(len(text), len(_FOLLOWUPS_WORD) - 1), 0, -1):
        tail = text[-size:].lower()
        if any(len(word) > size and word.startswith(tail) for word in _TAIL_WORDS):
            return len(text) - size
    return len(text)


def safe_text(text: str, *, final: bool, verbatim: bool) -> str:
    """Return the part of an unfinished line that can be released now.

    Holds back trailing spaces (an invalid marker takes the space before it), an
    unfinished ``[[`` marker, an unmatched inline code opener and a possible
    ``<followups`` prefix. With `final` only an unfinished marker is dropped.
    """
    if not final:
        text = text[: followups_hold(text)]
    limit = len(text)
    if not verbatim:
        marker = open_marker(text)
        if marker is not None:
            limit = min(limit, marker)
        if not final:
            limit = min(limit, _inline_hold(text))
    return text[:limit].rstrip(" \t")


def _inline_hold(text: str) -> int:
    """Where to stop for a lone ``[`` or an unmatched backtick opener."""
    limit = len(text)
    if text.endswith("["):
        limit -= 1
    _, unresolved = code_spans(text, partial=True)
    return limit if unresolved is None else min(limit, unresolved)


def _in_spans(pos: int, spans: list[tuple[int, int]]) -> bool:
    """True when `pos` lies inside one of the code spans."""
    return any(start <= pos < end for start, end in spans)


def render_text(text: str, resolve: Resolver) -> str:
    """Replace the markers of a line; markers inside inline code stay untouched.

    A marker with no valid label disappears together with the spaces before it.
    """
    if "[[" not in text:
        return text
    spans, _ = code_spans(text, partial=False)
    out: list[str] = []
    pos = 0
    for match in MARKER.finditer(text):
        if _in_spans(match.start(), spans):
            continue
        out.append(text[pos : match.start()])
        numbers = resolve(marker_labels(match.group(0))[:MAX_LABELS])
        if numbers:
            out.append(format_numbers(numbers))
        else:
            _strip_trailing_spaces(out)
        pos = match.end()
    out.append(text[pos:])
    return "".join(out)


def _strip_trailing_spaces(pieces: list[str]) -> None:
    """Remove trailing spaces and tabs from the end of a list of pieces."""
    while pieces:
        stripped = pieces[-1].rstrip(" \t")
        if stripped:
            pieces[-1] = stripped
            return
        pieces.pop()


def start_state(text: str, *, final: bool) -> StartState:
    """Decide whether a line starts with markers that must move before a bullet.

    Returns:
        ``move`` when the line starts with markers followed by a list bullet,
        ``normal`` when it does not, ``undecided`` when more text could change that.
    """
    body = text.lstrip(" \t")
    if not body:
        return "normal" if final else "undecided"
    if body[0] != "[":
        return "normal"
    if _MOVABLE.match(text):
        return "move"
    if final:
        return "normal"
    lead = _LEADING_MARKERS.match(text)
    rest = text[lead.end() :] if lead else body
    if lead and not rest:
        return "undecided"
    if len(rest) > MAX_MARKER_CHARS:
        return "normal"
    if _PARTIAL_START.fullmatch(rest) or (lead and _BULLET_PREFIX.fullmatch(rest)):
        return "undecided"
    return "normal"


def split_movable(text: str) -> tuple[str, str, int] | None:
    """Split ``<indent><markers><bullet ...>`` into indent, markers and bullet start."""
    match = _MOVABLE.match(text)
    if match is None:
        return None
    return match.group(1), match.group(2), match.end()
