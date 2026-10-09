"""Read models returned by authoring use cases (JSON shapes of the API contract)."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from app.modules.lms.domain.step_content import StepContent

from pydantic import BaseModel

# - - - People and outline - - -


class PersonRefView(BaseModel):
    """`PersonRef`: a person in lists and badges."""

    id: UUID
    first_name: str
    last_name: str


class OutlineStepView(BaseModel):
    """One step in an outline section."""

    step_id: UUID
    title: str
    badge: Literal["new", "changed", "removed", "mcp", "ai"] | None = None


class OutlineSectionView(BaseModel):
    """`OutlineSection`: a section with its steps."""

    id: str
    title: str
    steps: list[OutlineStepView]


# - - - Course and steps - - -


class CourseDraftView(BaseModel):
    """`CourseDraft`: the working copy of a course for the editor."""

    id: UUID
    slug: str
    title: str
    description: str
    visibility: Literal["public", "invite"]
    status: Literal["active", "archived"]
    invite_code: str | None
    lock_version: int
    draft_seq: int
    outline: list[OutlineSectionView]
    pending_count: int
    live_version: int | None
    my_permissions: list[str]


class StepDraftView(BaseModel):
    """`StepDraft`: the working copy of one step."""

    step_id: UUID
    course_id: UUID
    content: StepContent
    lock_version: int
    status: Literal["new", "changed", "unchanged"]
    updated_via: Literal["ui", "mcp", "ai"]
    updated_by: PersonRefView | None
    updated_at: datetime | None


class StepDiffView(BaseModel):
    """The live content of a step next to its draft."""

    live: StepContent | None
    draft: StepContent


class PreviewStepView(BaseModel):
    """`StepView` of the draft render used by previews."""

    step_id: UUID
    revision_id: str
    title: str
    blocks: list[dict[str, Any]]
    completed: bool
    preview: bool
    # Same lesson header numbers as `LearningStepView`; nothing is passed in a preview.
    blocks_total: int = 0
    blocks_passed: int = 0
    points_total: float = 0.0
    points_earned: float = 0.0


# - - - Revisions, pending changes, versions - - -


class RevisionItemView(BaseModel):
    """`RevisionItem`: a checkpoint or published state of a step."""

    id: UUID
    kind: Literal["publish", "checkpoint", "preview"]
    label: str | None
    created_by: PersonRefView
    created_at: datetime
    published: bool


class PendingStepView(BaseModel):
    """One pending step change."""

    step_id: UUID
    title: str
    change: Literal["added", "changed", "removed"]
    via_mcp: bool
    via_ai: bool = False


class PendingChangesView(BaseModel):
    """`PendingChanges`: what publishing would change."""

    draft_seq: int
    outline_changed: bool
    steps: list[PendingStepView]


class VersionChangesView(BaseModel):
    """Counts of what a version changed."""

    added: int
    changed: int
    removed: int
    outline_changed: bool


class VersionItemView(BaseModel):
    """`VersionItem`: one row of the version list."""

    number: int
    published_by: PersonRefView
    published_at: datetime
    note: str | None
    changes: VersionChangesView


class VersionMetaView(BaseModel):
    """Title and description at a version."""

    title: str
    description: str


class VersionDetailView(VersionItemView):
    """`VersionView`: a published version opened read-only."""

    meta: VersionMetaView
    outline: list[OutlineSectionView]


class CompareStepView(BaseModel):
    """How one step differs between two versions."""

    step_id: UUID
    title: str
    change: Literal["added", "changed", "removed", "same"]
    revision_a: UUID | None
    revision_b: UUID | None


class VersionCompareView(BaseModel):
    """`VersionCompare`: two versions side by side."""

    a: int
    b: int
    steps: list[CompareStepView]


# - - - Staff and settings - - -


class CourseStaffItemView(BaseModel):
    """`CourseStaffItem`: one staff member of a course."""

    user: PersonRefView
    role: str
    permissions: list[str]
    show_on_page: bool
    position: int


class InviteCodeView(BaseModel):
    """The new invite code of a course."""

    invite_code: str


class SectionCreatedView(BaseModel):
    """A section that was just added to the draft outline."""

    id: str
    title: str
    lock_version: int
    draft_seq: int


# - - - Applying a course plan - - -


class PlannedStepView(BaseModel):
    """What applying the plan does with one step (``step_id`` is null for new)."""

    title: str
    step_id: UUID | None
    action: Literal["new", "exists"]


class PlannedSectionView(BaseModel):
    """What applying the plan does with one section (``section_id`` null for new)."""

    title: str
    section_id: str | None
    action: Literal["new", "exists"]
    steps: list[PlannedStepView]


class CreatedSectionView(BaseModel):
    """A section the plan created."""

    id: str
    title: str


class CreatedStepView(BaseModel):
    """A step the plan created."""

    step_id: UUID
    section_id: str
    title: str


class PlanAppliedView(BaseModel):
    """The result (or, for a dry run, the preview) of applying a course plan."""

    created_sections: list[CreatedSectionView]
    created_steps: list[CreatedStepView]
    existing_sections: int
    existing_steps: int
    plan: list[PlannedSectionView]
    draft_seq: int
