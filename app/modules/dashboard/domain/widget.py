"""A dashboard widget: its kind, allowed sizes, position and colour."""

import re
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, field_validator, model_validator

WidgetKind = Literal[
    "timetable",
    "homework",
    "marks",
    "exams",
    "flashcards_due",
    "notebook_prompt",
    "attendance",
    "clock_next_lesson",
]
WidgetSize = Literal["1x1", "1x2", "2x1", "2x2", "2x4"]

# Sizes are columns x rows; the desktop grid has 4 columns, the phone grid 2.
WIDGET_SIZES: dict[str, set[str]] = {
    "timetable": {"2x1", "2x2", "2x4"},
    "homework": {"1x1", "2x1", "2x2"},
    "marks": {"1x1", "2x1", "2x2"},
    "exams": {"1x1", "2x1", "2x2"},
    "flashcards_due": {"1x1", "1x2", "2x1"},
    "notebook_prompt": {"2x1", "2x2"},
    "attendance": {"1x1", "2x1"},
    "clock_next_lesson": {"1x1", "2x1", "2x2"},
}
GRID_COLUMNS = 4
MAX_WIDGETS = 24
MAX_ROW = 200
MAX_CONFIG_VALUE = 500
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def size_span(size: str) -> tuple[int, int]:
    """Return (columns, rows) of a size such as "2x4"."""
    cols, rows = size.split("x")
    return int(cols), int(rows)


def _channel(value: int) -> float:
    c = value / 255
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def luminance(color: str) -> float:
    """Return the WCAG relative luminance of a #rrggbb colour."""
    r, g, b = (int(color[i : i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * _channel(r) + 0.7152 * _channel(g) + 0.0722 * _channel(b)


def contrast_ratio(a: str, b: str) -> float:
    """WCAG contrast ratio of two #rrggbb colours."""
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def text_on(background: str) -> str:
    """Return black or white text, whichever contrasts more with the background."""
    black, white = "#000000", "#FFFFFF"
    if contrast_ratio(background, white) >= contrast_ratio(background, black):
        return white
    return black


class Widget(BaseModel):
    """One tile of the dashboard grid."""

    id: UUID
    kind: WidgetKind
    size: WidgetSize
    x: int
    y: int
    color: str | None = None
    config: dict[str, str] = {}

    @field_validator("color")
    @classmethod
    def _color_is_hex(cls, value: str | None) -> str | None:
        if value is not None and not _HEX.match(value):
            raise ValueError("color must be #rrggbb")
        return value.upper() if value else value

    @field_validator("config")
    @classmethod
    def _config_is_small(cls, value: dict[str, str]) -> dict[str, str]:
        if len(value) > 10 or any(len(v) > MAX_CONFIG_VALUE for v in value.values()):
            raise ValueError("config is too large")
        return value

    @model_validator(mode="after")
    def _fits(self) -> Self:
        if self.size not in WIDGET_SIZES[self.kind]:
            raise ValueError(f"size {self.size} is not allowed for {self.kind}")
        cols, _ = size_span(self.size)
        if self.x < 0 or self.y < 0 or self.y > MAX_ROW:
            raise ValueError("position is out of the grid")
        if self.x + cols > GRID_COLUMNS:
            raise ValueError("widget does not fit the grid width")
        return self

    @property
    def text_color(self) -> str | None:
        """Readable text colour for the tile colour (WCAG contrast >= 4.5)."""
        return text_on(self.color) if self.color else None
