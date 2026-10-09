"""Text clean-up for the course kinds and for writing their output into a course.

The students of a course must never see a passage label (``S1:P3``), a citation chip,
raw HTML, a title numbered by the model or a ``#`` heading that fights with the step
title. The functions here are pure; the handlers apply them when the output is made
and the Apply conversions apply them again to whatever the author edited.
"""

import re
from typing import Final

from app.modules.notebooks.domain.artifacts.kind_support import clean_text, fit_text
from app.modules.notebooks.domain.artifacts.report_markdown import (
    strip_citation_marks,
    strip_html,
)

LESSON_HEADING_FLOOR: Final = 3  # a step title is shown above the blocks

_LABEL: Final = r"S\d+\s*:\s*P\d+"
_LABEL_LIST: Final = rf"{_LABEL}(?:\s*[,;]\s*{_LABEL})*"
_BRACKETED: Final = re.compile(rf"[ \t]*\[{{1,2}}\s*{_LABEL_LIST}\s*\]{{1,2}}")
_PARENTHESISED: Final = re.compile(rf"[ \t]*\(\s*{_LABEL_LIST}\s*\)")
_BARE: Final = re.compile(rf"[ \t]*\b{_LABEL}\b")
_IMAGE: Final = re.compile(r"!\[[^\]\n]*\]\([^)\n]*\)")
_WEB_LINK: Final = re.compile(r"\[([^\]\n]+)\]\(\s*(?:https?://|www\.)[^)\n]*\)")
_BLANK_RUNS: Final = re.compile(r"\n{3,}")
_TRAILING: Final = re.compile(r"[ \t]+$", re.MULTILINE)
_FENCE: Final = re.compile(r"^ {0,3}(```|~~~)")
_HEADING: Final = re.compile(r"^( {0,3})(#{1,6})([ \t]+\S.*)$")

_NUMBERING_WORDS: Final = (
    "section|step|lesson|module|chapter|unit|part|"
    "раздел|шаг|урок|модуль|глава|часть|тема|"
    "bo['ʻ’]?lim|qadam|dars|modul|bob|qism|mavzu"
)
_TITLE_NUMBER: Final = re.compile(
    rf"^\s*(?:(?:{_NUMBERING_WORDS})\s+)?\d+(?:\.\d+)*\s*[.):\-–—]+\s+", re.IGNORECASE
)
_TITLE_DECIMAL: Final = re.compile(r"^\s*\d+(?:\.\d+)+\s+")
_PLACEHOLDER_WORDS: Final = (
    "insert|add|fill|todo|tbd|placeholder|example here|вставьте|добавьте"
)
_PLACEHOLDERS: Final = (
    re.compile(rf"\[\s*(?:{_PLACEHOLDER_WORDS})\b[^\]]*\]", re.IGNORECASE),
    re.compile(r"<\s*(?:insert|placeholder)\b[^>]*>", re.IGNORECASE),
    re.compile(r"\{\{[^}\n]*\}\}"),
    re.compile(r"\blorem ipsum\b", re.IGNORECASE),
    re.compile(r"\b(?:TODO|TBD)\b"),
)


def strip_ref_labels(text: str) -> str:
    """Remove passage labels and citation chips from a text.

    ``[S1:P3]``, ``[[S1:P3]]``, ``[S1:P3, S1:P4]``, ``(S1:P3)``, a bare ``S1:P3`` and
    ``⟦1⟧`` all go, together with the spaces in front of them, so the sentence closes
    cleanly (``Light is absorbed [S1:P3].`` becomes ``Light is absorbed.``).
    """
    cleaned = strip_citation_marks(text)
    for pattern in (_BRACKETED, _PARENTHESISED, _BARE):
        cleaned = pattern.sub("", cleaned)
    return cleaned


def strip_links_and_images(markdown: str) -> str:
    """Drop images and keep only the text of web links (the model has no URLs)."""
    return _WEB_LINK.sub(r"\1", _IMAGE.sub("", markdown))


def demote_headings(markdown: str, floor: int = LESSON_HEADING_FLOOR) -> str:
    """Shift the headings so the shallowest one is ``floor`` (``###``) or deeper.

    Fenced code is left alone. A text whose headings are already deep enough is
    returned as it is; levels never go past ``######``.
    """
    lines = markdown.split("\n")
    levels = [level for _, level in _heading_lines(lines)]
    if not levels or min(levels) >= floor:
        return markdown
    shift = floor - min(levels)
    for index, level in _heading_lines(lines):
        match = _HEADING.match(lines[index])
        if match is not None:
            deeper = "#" * min(level + shift, 6)
            lines[index] = f"{match.group(1)}{deeper}{match.group(3)}"
    return "\n".join(lines)


def _heading_lines(lines: list[str]) -> list[tuple[int, int]]:
    """``(line index, level)`` of every heading outside fenced code."""
    found: list[tuple[int, int]] = []
    fence: str | None = None
    for index, line in enumerate(lines):
        marker = _FENCE.match(line)
        if marker is not None:
            fence = None if fence == marker.group(1) else (fence or marker.group(1))
            continue
        heading = _HEADING.match(line)
        if fence is None and heading is not None:
            found.append((index, len(heading.group(2))))
    return found


def clean_lesson_markdown(raw: str) -> str:
    """The Markdown of a text block as it is written into a course.

    No labels or chips, no raw HTML, no images or web links, headings from ``###``,
    no runs of blank lines, no trailing spaces.
    """
    text = strip_links_and_images(strip_html(strip_ref_labels(raw)))
    text = _TRAILING.sub("", demote_headings(text))
    return _BLANK_RUNS.sub("\n\n", text).strip()


def strip_numbering(title: str) -> str:
    """Remove ``1.``, ``2.3``, ``Lesson 4:`` and similar from the start of a title.

    A number that is part of the name (``3 types of triangles``, ``2D shapes``) is
    kept, and so is a title that would be empty without the prefix.
    """
    for pattern in (_TITLE_NUMBER, _TITLE_DECIMAL):
        stripped = pattern.sub("", title, count=1).strip()
        if stripped and stripped != title.strip():
            return stripped
    return title.strip()


def clean_item_title(raw: object, chars: int = 200) -> str:
    """A title of a section, step or lesson: one line, no labels, no numbering."""
    return fit_text(strip_numbering(strip_ref_labels(clean_text(raw))), chars=chars)


def find_placeholder(text: str) -> str | None:
    """The first placeholder found (``[insert example]``, ``TODO``, ...) or None."""
    for pattern in _PLACEHOLDERS:
        match = pattern.search(text)
        if match is not None:
            return match.group(0)[:40]
    return None
