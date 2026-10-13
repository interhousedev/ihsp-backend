"""Request and response models of presentation plans (PLAN)."""

from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from app.interfaces.http.v1.notebooks.schemas_studio import ArtifactItemResponse
from app.modules.notebooks.domain.artifacts.slide_outline import (
    OUTLINE_BULLET_CHARS,
    OUTLINE_BULLETS,
    OUTLINE_TITLE_CHARS,
)
from app.modules.notebooks.domain.entities import Artifact
from app.modules.notebooks.domain.limits import STUDIO_PROMPT_MAX_CHARS
from app.modules.notebooks.domain.presentation_plan import (
    PlanSlide,
    PresentationPlan,
)

from pydantic import BaseModel, Field

PLAN_EDIT_MAX_SLIDES = 40  # a plan may be saved above the deck limit, then trimmed


class PlanSlideBody(BaseModel):
    """One slide of an outline."""

    title: str = Field(min_length=1, max_length=OUTLINE_TITLE_CHARS)
    bullets: list[str] = Field(default_factory=list, max_length=OUTLINE_BULLETS)

    def to_slide(self) -> PlanSlide:
        """The domain slide (bullets clipped)."""
        return PlanSlide(
            title=self.title, bullets=[b[:OUTLINE_BULLET_CHARS] for b in self.bullets]
        )


class PlanCreateBody(BaseModel):
    """POST /v1/notebooks/{id}/presentation-plans."""

    prompt: str | None = Field(default=None, max_length=STUDIO_PROMPT_MAX_CHARS)
    """What the deck is about (optional focus)."""
    source_ids: list[UUID] | None = None
    """The sources to plan from; null: the notebook's selection."""
    slide_count: int | None = Field(default=None, ge=3, le=PLAN_EDIT_MAX_SLIDES)
    """About how many slides; the plan never exceeds `max_slides`."""
    format: Literal["presenter", "detailed"] = "presenter"
    """The deck's format, kept for "Generate"."""


class PlanUpdateBody(BaseModel):
    """PATCH /v1/notebooks/{id}/presentation-plans/{pid}: what is sent is replaced."""

    title: str | None = Field(default=None, max_length=255)
    slides: list[PlanSlideBody] | None = Field(
        default=None, max_length=PLAN_EDIT_MAX_SLIDES
    )
    """The whole outline in its new order (edited, deleted and moved slides)."""


class PlanSlideResponse(BaseModel):
    """One slide of an outline."""

    title: str
    bullets: list[str]


class PresentationPlanResponse(BaseModel):
    """`PresentationPlan`: a slide outline confirmed before its deck is made."""

    id: UUID
    notebook_id: UUID
    title: str
    slides: list[PlanSlideResponse]
    status: Literal["draft", "confirmed"]
    max_slides: int
    """The most slides a deck may have; a longer plan must be trimmed first."""
    over_limit: bool
    artifact_id: UUID | None
    """The deck made from the plan (after "Generate")."""
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_entity(cls, plan: PresentationPlan) -> Self:
        """Build from the plan entity."""
        return cls(
            id=plan.id,
            notebook_id=plan.notebook_id,
            title=plan.title,
            slides=[
                PlanSlideResponse(title=s.title, bullets=list(s.bullets))
                for s in plan.slides
            ],
            status=plan.status.value,
            max_slides=plan.max_slides,
            over_limit=plan.over_limit,
            artifact_id=plan.artifact_id,
            created_at=plan.created_at,
            updated_at=plan.updated_at,
        )


class PlanConfirmResponse(BaseModel):
    """The confirmed plan and the deck that is being generated."""

    plan: PresentationPlanResponse
    artifact: ArtifactItemResponse

    @classmethod
    def from_result(cls, plan: PresentationPlan, artifact: Artifact) -> Self:
        """Build from the use case result."""
        return cls(
            plan=PresentationPlanResponse.from_entity(plan),
            artifact=ArtifactItemResponse.from_entity(artifact),
        )
