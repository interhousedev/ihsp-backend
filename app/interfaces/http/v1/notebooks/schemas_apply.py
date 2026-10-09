"""Request and response models of "Apply to the course" (workspace Studio outputs).

``POST /v1/notebooks/{id}/artifacts/{aid}/apply-preview`` answers with an
`ApplyPreviewResponse` (a dry run), ``.../apply`` with an `ApplyResultResponse`.
Both take an `ApplyBody`. A ``Block`` is a block of the LMS step content; the models
are permissive (unknown keys pass through) but typed, so the generated client knows
the shape of the blocks it shows in the diff.
"""

from typing import Annotated, Literal, Self
from uuid import UUID

from app.modules.notebooks.application.apply_views import (
    ApplyPreviewView,
    ApplyRequest,
    ApplyResultView,
    PlanPreview,
    StepPreview,
)
from app.shared.contracts.lms_blocks import CoursePlanInput, StepDraftInput

from pydantic import BaseModel, ConfigDict, Field


class ApplyBody(BaseModel):
    """What the author chose in the Apply dialog (all fields optional).

    A new step is created when no ``target_step_id`` is given and a
    ``target_section_id`` is. A lesson draft made for a step (its ``step_id``
    option) goes there by default. ``plan`` and ``draft`` carry the author's edits of
    the output; they are validated again on the server.
    """

    target_step_id: UUID | None = Field(
        default=None, description="The draft step to write into."
    )
    target_section_id: str | None = Field(
        default=None,
        description="The section for a NEW step (used when no step id is given).",
    )
    mode: Literal["append", "replace"] | None = Field(
        default=None,
        description="Default: replace for a lesson draft, append for a quiz or cards.",
    )
    plan: CoursePlanInput | None = Field(
        default=None, description="The edited course plan (course_plan only)."
    )
    draft: StepDraftInput | None = Field(
        default=None, description="The edited lesson (lesson_draft only)."
    )
    add_briefs: bool = Field(
        default=False,
        description="A new step of a plan gets its goals and summary as a text block.",
    )
    lock_version: int | None = Field(
        default=None,
        ge=0,
        description="The step's lock version from the preview; a changed draft is 409.",
    )

    def to_request(self) -> ApplyRequest:
        """The application request."""
        return ApplyRequest(
            target_step_id=self.target_step_id,
            target_section_id=self.target_section_id,
            mode=self.mode,
            plan=self.plan,
            draft=self.draft,
            add_briefs=self.add_briefs,
            lock_version=self.lock_version,
        )


# - - - Blocks of a step (the LMS StepContent shape) - - -


class _Loose(BaseModel):
    """Base of the block models: unknown keys are kept, not refused."""

    model_config = ConfigDict(extra="allow")


class BlockOption(_Loose):
    """An answer option of a choice question."""

    id: str = ""
    text: str
    correct: bool = False
    pinned: bool = False


class BlockAnswer(_Loose):
    """Accepted answers of a text or number question."""

    accepted: list[str] | None = None
    regex: str | None = None
    case_sensitive: bool = False
    value: float | None = None
    tolerance: float = 0.0


class BlockQuestion(_Loose):
    """A question of a test block."""

    id: str = ""
    type: Literal["single", "multiple", "text", "number"]
    prompt: str
    points: float = 1.0
    explanation: str | None = None
    options: list[BlockOption] | None = None
    answer: BlockAnswer | None = None


class BlockCard(_Loose):
    """A flash card."""

    id: str = ""
    front: str
    back: str


class TextBlock(_Loose):
    """A Markdown text block."""

    id: str = ""
    type: Literal["text"] = "text"
    markdown: str = ""


class TestBlock(_Loose):
    """A test block: its settings and questions."""

    __test__ = False  # not a pytest class, despite the name

    id: str = ""
    type: Literal["test"] = "test"
    config: dict[str, object] = Field(default_factory=dict)
    questions: list[BlockQuestion] = Field(default_factory=list)


class FlashcardsBlock(_Loose):
    """A flash cards block."""

    id: str = ""
    type: Literal["flashcards"] = "flashcards"
    cards: list[BlockCard] = Field(default_factory=list)


Block = Annotated[TextBlock | TestBlock | FlashcardsBlock, Field(discriminator="type")]


# - - - Preview - - -


class PlanStepPreviewResponse(BaseModel):
    """A step of the outline: it exists already, or it would be created."""

    title: str
    step_id: UUID | None
    action: Literal["new", "exists"]


class PlanSectionPreviewResponse(BaseModel):
    """A section of the outline with its steps."""

    title: str
    section_id: str | None
    action: Literal["new", "exists"]
    steps: list[PlanStepPreviewResponse]


class PlanPreviewResponse(BaseModel):
    """What applying a course plan would do to the draft outline."""

    sections: list[PlanSectionPreviewResponse]
    new_sections: int
    new_steps: int
    existing_steps: int

    @classmethod
    def from_view(cls, view: PlanPreview) -> Self:
        """Build from the use case view."""
        return cls.model_validate(view, from_attributes=True)


class StepPreviewResponse(BaseModel):
    """What applying a lesson, a quiz or a deck would do to one step.

    ``new_blocks`` are the blocks the step has afterwards in ``replace`` mode, and the
    blocks added after ``current_blocks`` in ``append`` mode. A new step has no
    ``step_id``, no ``lock_version`` and no ``current_blocks``.
    """

    step_id: UUID | None
    title: str
    lock_version: int | None
    mode: Literal["append", "replace"]
    current_blocks: list[Block] | None
    new_blocks: list[Block]

    @classmethod
    def from_view(cls, view: StepPreview) -> Self:
        """Build from the use case view."""
        return cls.model_validate(view, from_attributes=True)


class ApplyPreviewResponse(BaseModel):
    """The dry run of an Apply: what would change, what is wrong, what was reduced."""

    kind: Literal["course_plan", "lesson_draft", "quiz", "flashcards"]
    can_apply: bool
    problems: list[str] = Field(description="Why it cannot be applied (can_apply).")
    notes: list[str] = Field(description="What is reduced or left out; informational.")
    plan: PlanPreviewResponse | None = None
    step: StepPreviewResponse | None = None

    @classmethod
    def from_view(cls, view: ApplyPreviewView) -> Self:
        """Build from the use case view."""
        return cls.model_validate(
            {
                "kind": view.kind,
                "can_apply": view.can_apply,
                "problems": view.problems,
                "notes": view.notes,
                "plan": PlanPreviewResponse.from_view(view.plan) if view.plan else None,
                "step": StepPreviewResponse.from_view(view.step) if view.step else None,
            }
        )


# - - - Result - - -


class CreatedSectionResponse(BaseModel):
    """A section created by the Apply."""

    id: str
    title: str


class CreatedStepResponse(BaseModel):
    """A step created by the Apply."""

    step_id: UUID
    section_id: str
    title: str


class ApplyResultResponse(BaseModel):
    """What the Apply wrote into the draft."""

    kind: Literal["course_plan", "lesson_draft", "quiz", "flashcards"]
    created_sections: list[CreatedSectionResponse]
    created_steps: list[CreatedStepResponse]
    step_id: UUID | None
    lock_version: int | None
    draft_seq: int | None = Field(description="The draft counter after the write.")

    @classmethod
    def from_view(cls, view: ApplyResultView) -> Self:
        """Build from the use case view."""
        return cls.model_validate(
            {
                "kind": view.kind,
                "created_sections": view.created_sections,
                "created_steps": view.created_steps,
                "step_id": view.step_id,
                "lock_version": view.lock_version,
                "draft_seq": view.draft_seq,
            }
        )
