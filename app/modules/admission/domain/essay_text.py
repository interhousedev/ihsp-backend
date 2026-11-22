"""Essay text as blocks: paragraphs and scene-break transitions.

A paragraph is a run of lines ended by a blank line or a scene break. A scene break is a
short line of only punctuation (``* * *``, ``---``, ``___``, ``§``): a transition, never
a paragraph, and it splits the text even without blank lines around it.
"""

import re
from dataclasses import dataclass
from typing import Final

_BREAK_MAX: Final = 12
_NO_WORDS: Final = re.compile(r"[\W_]+")


@dataclass(frozen=True, slots=True)
class Paragraph:
    """A run of text lines."""

    text: str


@dataclass(frozen=True, slots=True)
class Transition:
    """A scene break line."""

    text: str


def is_scene_break(line: str) -> bool:
    """A short line with no letters or digits, only punctuation, symbols and spaces."""
    s = line.strip()
    return bool(s) and len(s) <= _BREAK_MAX and _NO_WORDS.fullmatch(s) is not None


def split_blocks(body: str) -> list[Paragraph | Transition]:
    """Split the body into paragraphs separated by blank lines and scene breaks."""
    blocks: list[Paragraph | Transition] = []
    run: list[str] = []

    def flush() -> None:
        text = "\n".join(run).strip()
        run.clear()
        if text:
            blocks.append(Paragraph(text))

    for line in body.splitlines():
        if not line.strip():
            flush()
        elif is_scene_break(line):
            flush()
            blocks.append(Transition(line.strip()))
        else:
            run.append(line)
    flush()
    return blocks


def paragraphs(body: str) -> list[str]:
    """The paragraph texts of the body, scene breaks left out."""
    return [b.text for b in split_blocks(body) if isinstance(b, Paragraph)]
