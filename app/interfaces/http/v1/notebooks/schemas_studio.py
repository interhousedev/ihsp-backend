"""Request and response models of the Studio routes (field names = § 4.4 contract).

There is no audio or video overview: `audio_overview` is neither a creatable nor a
listed kind, and the response keeps `has_assets` / `assets` only as constants for
the frozen web types.
"""

from datetime import datetime
from typing import Annotated, Any, Literal, Self
from uuid import UUID

from app.modules.notebooks.application.views import ArtifactDetailView
from app.modules.notebooks.domain.artifacts.kind_support import CommonOptions
from app.modules.notebooks.domain.artifacts.kinds.course_plan import CoursePlanOptions
from app.modules.notebooks.domain.artifacts.kinds.data_table import DataTableOptions
from app.modules.notebooks.domain.artifacts.kinds.flashcards import FlashcardsOptions
from app.modules.notebooks.domain.artifacts.kinds.infographic import InfographicOptions
from app.modules.notebooks.domain.artifacts.kinds.lesson_draft import (
    LessonDraftOptions,
)
from app.modules.notebooks.domain.artifacts.kinds.mind_map import MindMapOptions
from app.modules.notebooks.domain.artifacts.kinds.quiz import QuizOptions
from app.modules.notebooks.domain.artifacts.kinds.report import ReportOptions
from app.modules.notebooks.domain.artifacts.kinds.slides import SlidesOptions
from app.modules.notebooks.domain.entities import Artifact, ArtifactError
from app.modules.notebooks.domain.enums import ArtifactStatus, ReportFormat

from pydantic import BaseModel, Field

StudioKind = Literal[
    "report",
    "mind_map",
    "flashcards",
    "quiz",
    "data_table",
    "slides",
    "infographic",
    "course_plan",
    "lesson_draft",
]


class _CreateBase(BaseModel):
    """Fields of every creation request: the options and the focus text."""

    prompt: str | None = None
    options: CommonOptions

    def options_dict(self) -> dict[str, Any]:
        """The options as the use case takes them (JSON-safe, without nulls)."""
        return self.options.model_dump(mode="json", exclude_none=True)


class ReportCreate(_CreateBase):
    """A report; its `format` is required."""

    kind: Literal["report"]
    options: ReportOptions


class MindMapCreate(_CreateBase):
    """A mind map."""

    kind: Literal["mind_map"]
    options: MindMapOptions = Field(default_factory=MindMapOptions)


class FlashcardsCreate(_CreateBase):
    """A flash card deck."""

    kind: Literal["flashcards"]
    options: FlashcardsOptions = Field(default_factory=FlashcardsOptions)


class QuizCreate(_CreateBase):
    """A quiz."""

    kind: Literal["quiz"]
    options: QuizOptions = Field(default_factory=QuizOptions)


class DataTableCreate(_CreateBase):
    """A data table."""

    kind: Literal["data_table"]
    options: DataTableOptions = Field(default_factory=DataTableOptions)


class SlidesCreate(_CreateBase):
    """A slide deck."""

    kind: Literal["slides"]
    options: SlidesOptions = Field(default_factory=SlidesOptions)


class InfographicCreate(_CreateBase):
    """An infographic."""

    kind: Literal["infographic"]
    options: InfographicOptions = Field(default_factory=InfographicOptions)


class CoursePlanCreate(_CreateBase):
    """A course plan (course workspaces only)."""

    kind: Literal["course_plan"]
    options: CoursePlanOptions = Field(default_factory=CoursePlanOptions)


class LessonDraftCreate(_CreateBase):
    """The blocks of one lesson (course workspaces only)."""

    kind: Literal["lesson_draft"]
    options: LessonDraftOptions = Field(default_factory=LessonDraftOptions)


ArtifactCreate = Annotated[
    ReportCreate
    | MindMapCreate
    | FlashcardsCreate
    | QuizCreate
    | DataTableCreate
    | SlidesCreate
    | InfographicCreate
    | CoursePlanCreate
    | LessonDraftCreate,
    Field(discriminator="kind"),
]


class RenameArtifactBody(BaseModel):
    """PATCH /v1/notebooks/{id}/artifacts/{aid}."""

    title: str


class ProgressBody(BaseModel):
    """PUT .../progress: the state is opaque to the server (at most 16 KB)."""

    state: dict[str, Any]


class SlidesBody(BaseModel):
    """PUT .../slides: the edited deck, checked slide by slide by the use case."""

    slides: list[dict[str, Any]]


class SlideChange(BaseModel):
    """One instruction of a revision."""

    slide_id: str
    instruction: str


class ReviseSlidesBody(BaseModel):
    """POST .../slides/revise."""

    changes: list[SlideChange]


class FlashcardSetResponse(BaseModel):
    """The flash card set made from a deck; `created` is false when it existed."""

    set_id: UUID
    created: bool


def _item_fields(artifact: Artifact) -> dict[str, Any]:
    """The `ArtifactItem` fields of an entity (shared with the detail)."""
    return {
        "id": artifact.id,
        "notebook_id": artifact.notebook_id,
        "kind": artifact.kind.value,
        "format": artifact.format,
        "title": artifact.title,
        "status": artifact.status,
        "error": artifact.error,
        "options": artifact.options,
        "prompt": artifact.prompt,
        "source_count": len(artifact.source_ids),
        "sampled": artifact.sampled,
        "unread": artifact.unread,
        "progress": artifact.progress,
        "parent_id": artifact.parent_id,
        "flashcard_set_id": artifact.flashcard_set_id,
        "created_at": artifact.created_at,
        "finished_at": artifact.finished_at,
    }


class _ArtifactBase(BaseModel):
    """The `ArtifactItem` fields, shared by the list item and the detail."""

    id: UUID
    notebook_id: UUID
    kind: StudioKind
    format: ReportFormat | None
    title: str
    status: ArtifactStatus
    error: ArtifactError | None
    options: dict[str, Any]
    prompt: str | None
    source_count: int
    sampled: bool
    unread: bool
    progress: int | None
    has_assets: bool = False  # always false: there is no audio overview
    parent_id: UUID | None
    flashcard_set_id: UUID | None
    created_at: datetime
    finished_at: datetime | None


class ArtifactItemResponse(_ArtifactBase):
    """`ArtifactItem`: an output without its content."""

    @classmethod
    def from_entity(cls, artifact: Artifact) -> Self:
        """Build from the artifact entity."""
        return cls(**_item_fields(artifact))


class ArtifactDetailResponse(_ArtifactBase):
    """`ArtifactDetail`: the item, the document, its references and the progress."""

    content: dict[str, Any] | None
    refs_index: dict[str, Any]
    source_map: dict[str, str]
    progress_state: dict[str, Any] | None
    assets: list[dict[str, Any]] = Field(default_factory=list)  # always empty

    @classmethod
    def from_view(cls, view: ArtifactDetailView) -> Self:
        """Build from the use case view."""
        artifact = view.artifact
        return cls(
            **_item_fields(artifact),
            content=artifact.content,
            refs_index=artifact.refs_index or {},
            source_map=artifact.source_map,
            progress_state=view.progress_state,
        )


class AttachArtifactBody(BaseModel):
    """Attach a ready output to a lesson as a file."""

    lesson_id: UUID
    role: Literal["material", "attachment"] = "material"


class AttachedResourceResponse(BaseModel):
    """The lesson resource that was created from an output."""

    link_id: UUID
    lesson_id: UUID
    title: str
    short_url: str
