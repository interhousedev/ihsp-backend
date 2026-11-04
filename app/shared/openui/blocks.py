"""Finding OpenUI blocks (```openui fenced code) in the Markdown of an answer."""

import re
from dataclasses import dataclass
from typing import Literal

from app.shared.openui.catalog import load_catalog

PartKind = Literal["text", "block", "pending"]


@dataclass(frozen=True, slots=True)
class Part:
    """Plain Markdown, a closed block (its source) or an unfinished block."""

    kind: PartKind
    text: str
    raw: str = ""  # a block with its fence, as written


# Up to three spaces of indent, as CommonMark allows and as the web splitter
# (`packages/features-core/src/openui/split.ts`) reads it; four spaces is code.
_INDENT = r"[ \t]{0,3}"


def _fence() -> re.Pattern[str]:
    name = re.escape(load_catalog().fence)
    return re.compile(
        rf"^{_INDENT}```{name}[ \t]*\n(.*?)^{_INDENT}```[ \t]*$\n?", re.M | re.S
    )


def _opening() -> re.Pattern[str]:
    return re.compile(rf"^{_INDENT}```{re.escape(load_catalog().fence)}[ \t]*$", re.M)


def split_blocks(text: str) -> list[Part]:
    """Split an answer into text and blocks; a trailing open fence is `pending`."""
    parts: list[Part] = []
    pos = 0
    for match in _fence().finditer(text):
        if match.start() > pos:
            parts.append(Part("text", text[pos : match.start()]))
        parts.append(Part("block", match.group(1), match.group()))
        pos = match.end()
    rest = text[pos:]
    opening = _opening().search(rest)
    if opening is not None:
        if opening.start() > 0:
            parts.append(Part("text", rest[: opening.start()]))
        parts.append(Part("pending", rest[opening.end() :].lstrip("\n")))
    elif rest:
        parts.append(Part("text", rest))
    return parts


def fenced(source: str) -> str:
    """The block as fenced Markdown."""
    body = source if source.endswith("\n") else source + "\n"
    return f"```{load_catalog().fence}\n{body}```"


def unfence(text: str) -> str:
    """The source of a block answered with or without its fence."""
    parts = [p for p in split_blocks(text.strip()) if p.kind == "block"]
    if parts:
        return parts[0].text
    stripped = re.sub(r"^```[a-z-]*\n|```$", "", text.strip())
    return stripped.strip() + "\n"
