"""Plain text for slides: the viewer draws strings, not Markdown.

Models often write Markdown (``**bold**``, ``# Heading``, ``- item``) or put the
citation markers of chat answers (``[[S1:P4]]``) into slide texts. On a slide those
show up as stray characters, and a marker in the text is a citation the viewer cannot
resolve. `slide_text` removes them; `inline_labels` finds the labels so that they can
be moved to the slide's `refs`.
"""

import re
from collections.abc import Iterable

from app.modules.notebooks.domain.artifacts.kind_support import fit_text
from app.modules.notebooks.domain.artifacts.refs import normalize_label

# [[S1:P4]], [S1:P4], (S1:P4), [S1:P4, S2:P1], 【S1:P4】 and loose spellings of them.
_LABEL = r"S\s*\d+\s*[:.\-]?\s*P\s*\d+"
_MARKER = re.compile(
    rf"\s*[\[(【]+\s*{_LABEL}(?:\s*[,;]\s*{_LABEL})*\s*[\])】]+", re.IGNORECASE
)
_ONE_LABEL = re.compile(_LABEL, re.IGNORECASE)
_EMPHASIS = re.compile(r"(\*\*|__)(?=\S)(.+?)(?<=\S)\1")
_CODE = re.compile(r"`([^`]+)`")
_HEADING = re.compile(r"^#{1,6}\s+")
_BULLET = re.compile(r"^(?:[-*•‣▪●◦–—]|\d{1,2}[.)])\s+")


def inline_labels(texts: Iterable[str | None]) -> list[str]:
    """Labels written inside the texts as citation markers, in order."""
    found: list[str] = []
    for text in texts:
        for marker in _MARKER.finditer(text or ""):
            found.extend(normalize_label(m) for m in _ONE_LABEL.findall(marker[0]))
    return found


def slide_text(
    value: object,
    *,
    words: int | None = None,
    chars: int | None = None,
    item: bool = False,
) -> str:
    """Clean one slide text: no markers, no Markdown, whitespace collapsed, capped.

    `item` also removes a leading list marker ("- ", "• ", "1. "), which the viewer
    draws itself.
    """
    if not isinstance(value, str):
        return ""
    text = _MARKER.sub("", value)
    text = _CODE.sub(r"\1", _EMPHASIS.sub(r"\2", text))
    text = _HEADING.sub("", text.strip())
    if item:
        text = _BULLET.sub("", text)
    return fit_text(text, words=words, chars=chars)
