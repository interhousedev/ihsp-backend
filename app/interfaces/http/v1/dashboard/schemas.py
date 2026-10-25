"""Request and response bodies of the dashboard routes."""

from typing import Self
from uuid import UUID

from app.modules.dashboard.domain.layout import Layout
from app.modules.dashboard.domain.widget import (
    MAX_WIDGETS,
    Widget,
    WidgetKind,
    WidgetSize,
)

from pydantic import BaseModel, Field


class WidgetResponse(BaseModel):
    """A widget with the computed text colour."""

    id: UUID
    kind: WidgetKind
    size: WidgetSize
    x: int
    y: int
    color: str | None = None
    config: dict[str, str] = Field(default_factory=dict)

    text_color: str | None

    @classmethod
    def from_widget(cls, widget: Widget) -> Self:
        """Build from the domain widget."""
        return cls(**widget.model_dump(), text_color=widget.text_color)


class DashboardResponse(BaseModel):
    """The layout; version 0 is the default one (never saved)."""

    version: int
    widgets: list[WidgetResponse]

    @classmethod
    def from_layout(cls, layout: Layout) -> Self:
        """Build from the domain layout."""
        return cls(
            version=layout.version,
            widgets=[WidgetResponse.from_widget(w) for w in layout.widgets],
        )


class SaveDashboardRequest(BaseModel):
    """Replace the layout if `version` is the stored one."""

    version: int = Field(ge=0)
    widgets: list[Widget] = Field(max_length=MAX_WIDGETS)
