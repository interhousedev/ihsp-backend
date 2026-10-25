"""Request and result types of "Apply to the course" (the HTTP `ApplyBody` and friends).

Plain dataclasses: the HTTP layer maps its pydantic schemas to and from them, and the
`NotebooksCommands.apply_artifact` contract returns `ApplyResultView.as_dict()`.
"""

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from app.shared.contracts.lms_blocks import CoursePlanInput, StepDraftInput

APPEND = "append"
REPLACE = "replace"
MODES = (APPEND, REPLACE)


@dataclass(frozen=True, slots=True)
class ApplyRequest:
    """What the author chose in the Apply dialog.

    ``plan`` and ``draft`` carry the author's edits of the output; ``lock_version`` is
    the one the preview showed (a changed draft then answers 409); a missing
    ``mode`` is ``replace`` for a lesson draft and ``append`` for a quiz or a deck.
    """

    target_step_id: UUID | None = None
    target_section_id: str | None = None
    mode: str | None = None
    plan: CoursePlanInput | None = None
    draft: StepDraftInput | None = None
    add_briefs: bool = False
    lock_version: int | None = None


@dataclass(frozen=True, slots=True)
class PlanStepPreview:
    """A step of the outline: exists in the draft already, or would be created."""

    title: str
    step_id: str | None
    action: str  # new | exists


@dataclass(frozen=True, slots=True)
class PlanSectionPreview:
    """A section of the outline with its steps."""

    title: str
    section_id: str | None
    action: str  # new | exists
    steps: list[PlanStepPreview] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class PlanPreview:
    """What applying a course plan would do to the draft outline."""

    sections: list[PlanSectionPreview]
    new_sections: int
    new_steps: int
    existing_steps: int


@dataclass(frozen=True, slots=True)
class StepPreview:
    """What applying a lesson, a quiz or a deck would do to one step.

    ``new_blocks`` are the blocks the step has afterwards in ``replace`` mode and the
    blocks added after ``current_blocks`` in ``append`` mode. A new step has no
    ``step_id``, no ``lock_version`` and no ``current_blocks``.
    """

    step_id: UUID | None
    title: str
    lock_version: int | None
    mode: str
    current_blocks: list[dict[str, Any]] | None
    new_blocks: list[dict[str, Any]]


@dataclass(frozen=True, slots=True)
class ApplyPreviewView:
    """The dry run: what would change, what is wrong, what was reduced."""

    kind: str
    can_apply: bool
    problems: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    plan: PlanPreview | None = None
    step: StepPreview | None = None


@dataclass(frozen=True, slots=True)
class ApplyResultView:
    """What was written; ``draft_seq`` is None only when it could not be read."""

    kind: str
    created_sections: list[dict[str, Any]] = field(default_factory=list)
    created_steps: list[dict[str, Any]] = field(default_factory=list)
    step_id: UUID | None = None
    lock_version: int | None = None
    draft_seq: int | None = None

    def as_dict(self) -> dict[str, Any]:
        """The ``NotebooksCommands.apply_artifact`` result (JSON-safe)."""
        return {
            "kind": self.kind,
            "created_sections": self.created_sections,
            "created_steps": self.created_steps,
            "step_id": str(self.step_id) if self.step_id else None,
            "lock_version": self.lock_version,
            "draft_seq": self.draft_seq,
        }
