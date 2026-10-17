"""Request and response schemas of the authoring API (JSON is snake_case)."""

from collections.abc import Sequence
from typing import TypeVar
from uuid import UUID

from app.modules.lms.application.authoring.views import (
    CompareStepView,
    CourseDraftView,
    CourseStaffItemView,
    H5PLaunchView,
    H5PPackageView,
    InviteCodeView,
    OutlineSectionView,
    OutlineStepView,
    PendingChangesView,
    PendingStepView,
    PersonRefView,
    PreviewStepView,
    RevisionItemView,
    StepDiffView,
    StepDraftView,
    VersionChangesView,
    VersionCompareView,
    VersionDetailView,
    VersionItemView,
    VersionMetaView,
    VideoStreamView,
)
from app.modules.lms.domain.authoring.enums import CourseStatus, Visibility
from app.modules.lms.domain.authoring.outline import OutlineOp
from app.modules.lms.domain.step_content import StepContent

from pydantic import BaseModel, Field

T = TypeVar("T", bound=BaseModel)

# - - - Responses (same JSON as the application views) - - -


class PersonRefResponse(PersonRefView):
    """`PersonRef`."""


class OutlineStepResponse(OutlineStepView):
    """A step in an outline section."""


class OutlineSectionResponse(OutlineSectionView):
    """`OutlineSection`."""


class CourseDraftResponse(CourseDraftView):
    """`CourseDraft`."""


class StepDraftResponse(StepDraftView):
    """`StepDraft`."""


class StepDiffResponse(StepDiffView):
    """Live content next to the draft content of a step."""


class PreviewStepResponse(PreviewStepView):
    """`StepView` of a draft render."""


class H5PPackageResponse(H5PPackageView):
    """An uploaded H5P package."""


class H5PLaunchResponse(H5PLaunchView):
    """The signed base URL of an H5P package."""


class VideoStreamResponse(VideoStreamView):
    """A short-lived URL that streams an uploaded video."""


class RevisionItemResponse(RevisionItemView):
    """`RevisionItem`."""


class PendingStepResponse(PendingStepView):
    """One pending step change."""


class PendingChangesResponse(PendingChangesView):
    """`PendingChanges`."""


class VersionChangesResponse(VersionChangesView):
    """Counts of what a version changed."""


class VersionItemResponse(VersionItemView):
    """`VersionItem`."""


class VersionMetaResponse(VersionMetaView):
    """Title and description at a version."""


class VersionResponse(VersionDetailView):
    """`VersionView`."""


class CompareStepResponse(CompareStepView):
    """How one step differs between two versions."""


class VersionCompareResponse(VersionCompareView):
    """`VersionCompare`."""


class CourseStaffItemResponse(CourseStaffItemView):
    """`CourseStaffItem`."""


class InviteCodeResponse(InviteCodeView):
    """The rotated invite code."""


def respond(model: type[T], view: BaseModel) -> T:
    """Convert an application view into the response model of the route."""
    return model.model_validate(view, from_attributes=True)


def respond_list(model: type[T], views: Sequence[BaseModel]) -> list[T]:
    """Convert a list of application views."""
    return [respond(model, view) for view in views]


# - - - Request bodies - - -


class CreateCourseBody(BaseModel):
    """Create a course."""

    title: str = Field(min_length=1, max_length=200)
    slug: str = Field(min_length=3, max_length=60)
    visibility: Visibility


class UpdateMetaBody(BaseModel):
    """Save the draft title and description."""

    title: str = Field(min_length=1, max_length=200)
    description: str = Field(max_length=50_000)
    lock_version: int = Field(ge=0)


class OutlineBody(BaseModel):
    """Apply outline operations."""

    ops: list[OutlineOp] = Field(min_length=1, max_length=200)
    lock_version: int = Field(ge=0)


class CreateStepBody(BaseModel):
    """Create a step in a section."""

    section_id: str
    title: str = Field(min_length=1, max_length=200)
    position: int | None = Field(default=None, ge=0)


class SaveStepDraftBody(BaseModel):
    """Save the draft content of a step."""

    content: StepContent
    lock_version: int = Field(ge=0)


class CheckpointBody(BaseModel):
    """Name a checkpoint."""

    label: str = Field(min_length=1, max_length=120)


class RestoreRevisionBody(BaseModel):
    """Choose the revision to restore."""

    revision_id: UUID


class PublishBody(BaseModel):
    """Publish the draft the publisher reviewed."""

    draft_seq: int = Field(ge=0)
    note: str | None = Field(default=None, max_length=1000)


class AddStaffBody(BaseModel):
    """Add a staff member by login."""

    login: str = Field(min_length=1, max_length=255)
    role: str = Field(min_length=1, max_length=40)
    permissions: list[str] | None = None
    show_on_page: bool = True
    position: int = Field(default=0, ge=0, le=32_767)


class UpdateStaffBody(BaseModel):
    """Change a staff member; omitted fields stay as they are."""

    role: str | None = Field(default=None, min_length=1, max_length=40)
    permissions: list[str] | None = None
    show_on_page: bool | None = None
    position: int | None = Field(default=None, ge=0, le=32_767)


class SettingsBody(BaseModel):
    """Change course settings; omitted fields stay as they are."""

    visibility: Visibility | None = None
    status: CourseStatus | None = None
    cover_file_id: UUID | None = None
