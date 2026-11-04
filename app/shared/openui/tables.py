"""Turns Markdown tables of an answer into Table blocks where that loses nothing.

A table stays Markdown when it does not fit the catalogue or when a cell holds what a
block cell cannot show: a link, a citation marker or a formula.
"""

import json
import re
from typing import Final

from app.shared.openui.blocks import fenced, split_blocks
from app.shared.openui.catalog import load_catalog
from app.shared.openui.validate import validate_block

_SEPARATOR: Final = re.compile(r"^\s*\|?\s*:?-{1,}:?\s*(?:\|\s*:?-{1,}:?\s*)*\|?\s*$")
_RICH_CELL: Final = re.compile(r"\]\(|\[\[|\[S\d|\$.*\$|\\\(|<[a-zA-Z/]")
_EMPHASIS: Final = re.compile(r"\*\*|__|`")
_CODE_FENCE: Final = "```"


def _cells(line: str) -> list[str]:
    body = line.strip().removeprefix("|").removesuffix("|")
    return [_EMPHASIS.sub("", c).strip() for c in re.split(r"(?<!\\)\|", body)]


def _is_row(line: str) -> bool:
    return "|" in line and bool(line.strip())


def _block(header: list[str], rows: list[list[str]]) -> str | None:
    if any(_RICH_CELL.search(c) for c in [*header, *(c for r in rows for c in r)]):
        return None
    if any(len(r) != len(header) for r in rows) or not rows:
        return None
    columns = json.dumps(header, ensure_ascii=False)
    data = json.dumps(rows, ensure_ascii=False)
    source = f"root = Stack([t])\nt = Table({columns}, {data})\n"
    return fenced(source) if not validate_block(source, "chat") else None


def _convert_text(text: str, room: int) -> tuple[str, int]:
    """Convert tables outside code; `room` is how many more blocks may be added."""
    lines = text.split("\n")
    out: list[str] = []
    index = 0
    in_code = False
    while index < len(lines):
        line = lines[index]
        if line.lstrip().startswith(_CODE_FENCE):
            in_code = not in_code
        is_table = (
            not in_code
            and room > 0
            and _is_row(line)
            and index + 1 < len(lines)
            and _SEPARATOR.match(lines[index + 1])
            and "-" in lines[index + 1]
        )
        if not is_table:
            out.append(line)
            index += 1
            continue
        end = index + 2
        while end < len(lines) and _is_row(lines[end]):
            end += 1
        block = _block(_cells(line), [_cells(row) for row in lines[index + 2 : end]])
        if block is None:
            out.extend(lines[index:end])
        else:
            out.append(block.rstrip("\n"))
            room -= 1
        index = end
    return "\n".join(out), room


def markdown_tables_to_blocks(text: str) -> str:
    """The answer with its Markdown tables as Table blocks, within the block limit."""
    if "|" not in text:
        return text
    parts = split_blocks(text)
    room = load_catalog().limits["max_blocks"]
    room -= sum(1 for part in parts if part.kind == "block")
    out: list[str] = []
    for part in parts:
        if part.kind == "text":
            converted, room = _convert_text(part.text, room)
            out.append(converted)
        else:
            out.append(part.raw)
    return "".join(out)
