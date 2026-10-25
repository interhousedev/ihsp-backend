"""Presentation plans (PLAN): a slide outline the student confirms before the deck.

A plan is a numbered list of slides (a title and 2 to 5 bullets each). The student
may edit titles and bullets, delete and reorder slides; `Generate` then makes the
deck from the edited outline. A plan never holds more slides than the longest deck
(`PLAN_MAX_SLIDES`); a longer plan is refused until it is trimmed.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Final
from uuid import UUID

from app.modules.notebooks.domain.artifacts.kinds.slides import (
    MIN_SLIDES,
    SLIDE_COUNTS,
    Length,
)
from app.modules.notebooks.domain.artifacts.slide_outline import (
    OUTLINE_TITLE_CHARS,
    PlanSlide,
    outline_text,
)
from app.modules.notebooks.domain.artifacts.slides_shape import TOLERANCE

__all__ = [
    "PLAN_MAX_SLIDES",
    "PLAN_MIN_SLIDES",
    "PlanSlide",
    "PlanStatus",
    "PresentationPlan",
    "clean_slides",
    "length_for",
    "outline_text",
    "over_limit",
]

PLAN_MAX_SLIDES: Final = SLIDE_COUNTS["long"] + TOLERANCE
PLAN_MIN_SLIDES: Final = MIN_SLIDES
PLAN_PROMPT_CHARS: Final = 1000


class PlanStatus(StrEnum):
    """A draft can be edited; a confirmed plan has its deck."""

    DRAFT = "draft"
    CONFIRMED = "confirmed"


@dataclass(slots=True)
class PresentationPlan:
    """A slide outline of a notebook, owned by the student who asked for it."""

    id: UUID
    notebook_id: UUID
    owner_id: UUID
    title: str
    slides: list[PlanSlide]
    created_at: datetime
    updated_at: datetime
    status: PlanStatus = PlanStatus.DRAFT
    prompt: str | None = None
    source_ids: list[UUID] = field(default_factory=list)
    format: str = "presenter"
    artifact_id: UUID | None = None

    @property
    def max_slides(self) -> int:
        """The most slides a deck may have."""
        return PLAN_MAX_SLIDES

    @property
    def over_limit(self) -> bool:
        """Whether the plan must be trimmed before its deck can be generated."""
        return over_limit(self.slides)


def _flat(text: str) -> str:
    return " ".join(text.split())


def clean_slides(slides: list[PlanSlide]) -> list[PlanSlide]:
    """Collapse spaces, drop blank bullets and slides without a title."""
    cleaned: list[PlanSlide] = []
    for slide in slides:
        title = _flat(slide.title)[:OUTLINE_TITLE_CHARS]
        if not title:
            continue
        bullets = [_flat(b) for b in slide.bullets if _flat(b)]
        cleaned.append(PlanSlide(title=title, bullets=bullets))
    return cleaned


def over_limit(slides: list[PlanSlide]) -> bool:
    """Whether the plan has more slides than a deck may have."""
    return len(slides) > PLAN_MAX_SLIDES


def length_for(count: int) -> Length:
    """The deck length whose range (its count plus the tolerance) holds `count`."""
    if count <= SLIDE_COUNTS["short"] + TOLERANCE:
        return "short"
    if count <= SLIDE_COUNTS["default"] + TOLERANCE:
        return "default"
    return "long"
