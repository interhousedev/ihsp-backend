"""Pen, highlighter and shape markup of a reader's pages (private). Pure rules."""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from app.modules.library.domain.reader_errors import InvalidMarkupError

TOOLS = ("pen", "pencil", "highlighter", "rect", "ellipse", "line", "arrow")
SHAPE_TOOLS = frozenset({"rect", "ellipse", "line", "arrow"})
FREEHAND_TOOLS = frozenset({"pen", "pencil", "highlighter"})

MAX_PAGE = 100_000
MAX_SHAPES_PER_PAGE = 500
MAX_SHAPES = 5_000
MAX_POINTS = 2_000
MAX_TOTAL_POINTS = 200_000
MIN_WIDTH = 0.0001
MAX_WIDTH = 0.1
MAX_ID = 64

_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


@dataclass(frozen=True, slots=True)
class MarkupShape:
    """One stroke or figure; coordinates are fractions (0 to 1) of the page.

    `width` is the stroke width as a fraction of the page width, so everything
    scales with the zoom. A freehand tool keeps all its points; a figure keeps
    exactly two (the corners of a rectangle or ellipse, the ends of a line).
    """

    id: str
    tool: str
    color: str
    width: float
    points: tuple[tuple[float, float], ...]


@dataclass(frozen=True, slots=True)
class Markup:
    """All markup of one user on one item: shapes by page number (from 1)."""

    user_id: UUID
    item_id: UUID
    file_id: UUID
    pages: Mapping[int, tuple[MarkupShape, ...]]
    updated_at: datetime


def _bad(field: str) -> InvalidMarkupError:
    return InvalidMarkupError(params={"field": field})


def _number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise _bad(field)
    number = float(value)
    if number != number or number in (float("inf"), float("-inf")):
        raise _bad(field)
    return number


def parse_shape(raw: Mapping[str, Any]) -> MarkupShape:
    """A validated shape from its wire form; `InvalidMarkupError` otherwise."""
    shape_id = raw.get("id")
    if not isinstance(shape_id, str) or not 0 < len(shape_id) <= MAX_ID:
        raise _bad("id")
    tool = raw.get("tool")
    if tool not in TOOLS:
        raise _bad("tool")
    color = raw.get("color")
    if not isinstance(color, str) or not _COLOR.match(color):
        raise _bad("color")
    width = _number(raw.get("width"), "width")
    if not MIN_WIDTH <= width <= MAX_WIDTH:
        raise _bad("width")
    points = _parse_points(raw.get("points"), figure=tool in SHAPE_TOOLS)
    return MarkupShape(
        id=shape_id,
        tool=str(tool),
        color=color.lower(),
        width=width,
        points=points,
    )


def _parse_points(raw: Any, *, figure: bool) -> tuple[tuple[float, float], ...]:
    """The points of a shape: 1 to `MAX_POINTS`, exactly two for a figure."""
    if not isinstance(raw, Sequence) or isinstance(raw, str):
        raise _bad("points")
    if not 1 <= len(raw) <= MAX_POINTS or (figure and len(raw) != 2):
        raise _bad("points")
    points: list[tuple[float, float]] = []
    for point in raw:
        if not isinstance(point, Sequence) or isinstance(point, str):
            raise _bad("points")
        if len(point) != 2:
            raise _bad("points")
        x, y = _number(point[0], "points"), _number(point[1], "points")
        if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
            raise _bad("points")
        points.append((x, y))
    return tuple(points)


def parse_pages(
    raw: Mapping[str, Sequence[Mapping[str, Any]]],
) -> dict[int, tuple[MarkupShape, ...]]:
    """Validated pages from the wire form (page numbers are string keys).

    Empty pages are dropped; shape ids must be unique within a page.
    """
    pages: dict[int, tuple[MarkupShape, ...]] = {}
    total_points = 0
    for key, shapes in raw.items():
        page = _page_number(key)
        if len(shapes) > MAX_SHAPES_PER_PAGE:
            raise _bad("shapes")
        parsed = tuple(parse_shape(shape) for shape in shapes)
        total_points += sum(len(shape.points) for shape in parsed)
        if total_points > MAX_TOTAL_POINTS:
            raise _bad("points")
        if len({shape.id for shape in parsed}) != len(parsed):
            raise _bad("id")
        if parsed:
            pages[page] = parsed
    if sum(len(shapes) for shapes in pages.values()) > MAX_SHAPES:
        raise _bad("shapes")
    return pages


def _page_number(key: str) -> int:
    """A page number from its string key, in 1..`MAX_PAGE`."""
    if not key.isascii() or not key.isdigit():
        raise _bad("pages")
    page = int(key)
    if str(page) != key or not 1 <= page <= MAX_PAGE:
        raise _bad("pages")
    return page


def shape_to_dict(shape: MarkupShape) -> dict[str, Any]:
    """The JSON form of a shape (stored and sent over the wire)."""
    return {
        "id": shape.id,
        "tool": shape.tool,
        "color": shape.color,
        "width": shape.width,
        "points": [[x, y] for x, y in shape.points],
    }


def pages_to_dict(
    pages: Mapping[int, Sequence[MarkupShape]],
) -> dict[str, list[dict[str, Any]]]:
    """The JSON form of the pages, keyed by page number as text."""
    return {
        str(page): [shape_to_dict(s) for s in shapes] for page, shapes in pages.items()
    }
