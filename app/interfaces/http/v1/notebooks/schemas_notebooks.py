"""Request and response models of the notebook endpoints (names = § 4.4 contract)."""

from datetime import datetime
from typing import Annotated, Self
from uuid import UUID

from app.modules.notebooks.domain.entities import (
    AutoSettings,
    ChatConfig,
    Notebook,
    NotebookSummary,
)
from app.modules.notebooks.domain.enums import NotebookOrigin, SummaryStatus
from app.modules.notebooks.domain.limits import (
    EMOJI_MAX_CHARS,
    NOTEBOOK_TITLE_MAX_CHARS,
)

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


class CreateNotebookBody(BaseModel):
    """POST /v1/notebooks: both fields are optional (the AI names an untitled one)."""

    title: str | None = Field(default=None, max_length=NOTEBOOK_TITLE_MAX_CHARS)
    emoji: str | None = Field(default=None, max_length=EMOJI_MAX_CHARS)


class UpdateNotebookBody(BaseModel):
    """PATCH /v1/notebooks/{id}: only the keys that were sent are applied.

    `emoji: null` clears the emoji; a key that is absent changes nothing.
    """

    title: str | None = Field(default=None, max_length=NOTEBOOK_TITLE_MAX_CHARS)
    emoji: str | None = Field(default=None, max_length=EMOJI_MAX_CHARS)
    pinned: bool | None = None
    chat_config: ChatConfig | None = None


class UpdateAutoSettingsBody(BaseModel):
    """PATCH /v1/notebooks/{id}/auto: only the keys that were sent are applied.

    `exclude_source_ids` leaves lesson materials out for good (they stay out on
    every sync); `restore_refs` takes excluded materials back (their `ref_key`).
    """

    model_config = ConfigDict(extra="forbid")

    include_classmates: bool | None = None
    exclude_source_ids: list[UUID] | None = Field(default=None, max_length=100)
    restore_refs: list[Annotated[str, StringConstraints(max_length=300)]] | None = (
        Field(default=None, max_length=100)
    )


class ExcludedRefResponse(BaseModel):
    """A material left out of an auto notebook."""

    ref_key: str
    title: str


class AutoSettingsResponse(BaseModel):
    """`AutoSettings`: what the system syncs into a subject or lesson notebook."""

    include_classmates: bool
    excluded_refs: list[ExcludedRefResponse]
    synced_at: datetime | None

    @classmethod
    def from_entity(cls, settings: AutoSettings, synced_at: datetime | None) -> Self:
        """Build from the stored settings and the time of the last sync."""
        return cls(
            include_classmates=settings.include_classmates,
            excluded_refs=[
                ExcludedRefResponse(ref_key=x.ref_key, title=x.title)
                for x in settings.excluded_refs
            ],
            synced_at=synced_at,
        )


class SubjectNotebookSlotResponse(BaseModel):
    """`SubjectNotebookSlot`: a subject (and group) with its notebook, if made yet."""

    subject_id: UUID
    subject_name: str
    group_id: UUID | None  # teachers only
    group_name: str | None
    notebook_id: UUID | None  # None until the first open creates it
    source_count: int


class NotebookItemResponse(BaseModel):
    """`NotebookItem`."""

    id: UUID
    title: str
    emoji: str | None
    pinned: bool
    source_count: int
    last_opened_at: datetime | None
    updated_at: datetime
    origin: NotebookOrigin
    subject_id: UUID | None
    lesson_id: UUID | None
    group_id: UUID | None  # a teacher's subject notebook: its group
    course_id: UUID | None  # a course workspace or a student course notebook
    can_write: bool  # False for a course member who may only read

    @classmethod
    def from_entity(cls, notebook: Notebook) -> Self:
        """Build from the notebook entity."""
        return cls(
            id=notebook.id,
            title=notebook.title,
            emoji=notebook.emoji,
            pinned=notebook.pinned,
            source_count=notebook.source_count,
            last_opened_at=notebook.last_opened_at,
            updated_at=notebook.updated_at,
            origin=notebook.origin,
            subject_id=notebook.subject_id,
            lesson_id=notebook.lesson_id,
            group_id=notebook.group_id,
            course_id=notebook.course_id,
            can_write=notebook.can_write,
        )


class NotebookDetailResponse(NotebookItemResponse):
    """`NotebookDetail`: the item plus chat settings, summary and counters."""

    chat_config: ChatConfig
    summary: NotebookSummary | None
    summary_status: SummaryStatus
    ready_source_count: int
    selected_source_count: int
    created_at: datetime
    auto: AutoSettingsResponse | None

    @classmethod
    def from_entity(cls, notebook: Notebook) -> Self:
        """Build from the notebook entity."""
        return cls(
            **dict(NotebookItemResponse.from_entity(notebook)),
            chat_config=notebook.chat_config,
            summary=notebook.summary,
            summary_status=notebook.summary_status,
            ready_source_count=notebook.ready_source_count,
            selected_source_count=notebook.selected_source_count,
            created_at=notebook.created_at,
            auto=(
                AutoSettingsResponse.from_entity(
                    notebook.auto_settings, notebook.auto_synced_at
                )
                if notebook.auto_settings is not None
                else None
            ),
        )
