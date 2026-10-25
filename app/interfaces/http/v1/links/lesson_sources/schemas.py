"""Shapes of the lesson sources routes."""

from datetime import date
from typing import Literal
from uuid import UUID

from app.interfaces.http.v1.links.schemas import FileItem, file_item
from app.modules.links.application.lesson_sources import (
    EmisHidingState,
    LessonSourcePage,
    LessonSourceView,
)
from app.shared.contracts.links import EMIS_AUTHOR_ID

from pydantic import BaseModel


class LessonSourceItem(BaseModel):
    """A material of a lesson, seen from one of the lesson's groups."""

    link_id: UUID
    lesson_id: UUID
    group_id: UUID
    group_name: str
    date: date
    title: str
    name: str
    kind: Literal["url", "file"]
    short_url: str
    target_url: str | None
    file: FileItem | None
    hidden: bool
    hidden_by_rule: bool
    source: Literal["user", "emis"]

    @classmethod
    def from_view(cls, view: LessonSourceView) -> "LessonSourceItem":
        """Map a LessonSourceView."""
        link = view.resource.link
        assert link.lesson_id is not None
        return cls(
            link_id=link.id,
            lesson_id=link.lesson_id,
            group_id=view.group_id,
            group_name=view.group_name,
            date=view.date,
            title=view.title,
            name=view.resource.title,
            kind="file" if link.kind.value == "file" else "url",
            short_url=view.resource.short_url,
            target_url=link.target_url,
            file=file_item(view.resource.file, view.resource),
            hidden=link.is_hidden,
            hidden_by_rule=link.hidden_by_rule,
            source="emis" if link.owner_id == EMIS_AUTHOR_ID else "user",
        )


class LessonSourcePageResponse(BaseModel):
    """A page of lesson sources, by group then newest lesson first."""

    items: list[LessonSourceItem]
    total: int
    limit: int
    offset: int

    @classmethod
    def from_page(
        cls, page: LessonSourcePage, limit: int, offset: int
    ) -> "LessonSourcePageResponse":
        """Map a LessonSourcePage."""
        return cls(
            items=[LessonSourceItem.from_view(v) for v in page.items],
            total=page.total,
            limit=limit,
            offset=offset,
        )


class EmisSourcesHiddenBody(BaseModel):
    """Turn the "hide EMIS sources" rule of a group on or off."""

    hidden: bool


class EmisSourcesHiddenResponse(BaseModel):
    """Whether the rule is on; ``affected`` counts the resources a PUT changed."""

    hidden: bool
    affected: int

    @classmethod
    def from_state(cls, state: EmisHidingState) -> "EmisSourcesHiddenResponse":
        """Map an EmisHidingState."""
        return cls(hidden=state.hidden, affected=state.affected)
