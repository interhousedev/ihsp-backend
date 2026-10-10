"""Response models shared by the notebook routes (field names = § 4.4 contract)."""

from contextvars import ContextVar
from datetime import datetime
from typing import Any, Generic, Self, TypeVar
from uuid import UUID

from app.modules.notebooks.application.views import NotebookUsageView, UsagePartView
from app.modules.notebooks.domain.entities import Source
from app.modules.notebooks.domain.enums import SourceFailure, SourceKind, SourceStatus
from app.modules.notebooks.domain.modality import readable_by, source_modality

from pydantic import BaseModel, ConfigDict

T = TypeVar("T")


class PageResponse(BaseModel, Generic[T]):
    """`Page<T>`: a page of items and the cursor of the next one."""

    items: list[T]
    next_cursor: str | None = None


class UsagePartResponse(BaseModel):
    """Weighted tokens used against a limit."""

    used: int
    limit: int
    resets_at: datetime | None

    @classmethod
    def from_view(cls, view: UsagePartView) -> Self:
        """Build from the use case view."""
        return cls(used=view.used, limit=view.limit, resets_at=view.resets_at)


class BudgetResponse(BaseModel):
    """The session and the day budget."""

    session: UsagePartResponse
    day: UsagePartResponse


class QuotaResponse(BaseModel):
    """Daily count of outputs of one counter."""

    used: int
    limit: int
    resets_at: datetime


class NotebookUsageResponse(BaseModel):
    """`NotebookUsage`: budget, daily quotas and the outputs generating now.

    A counter that is switched off has a limit of 0 (clients hide it).
    """

    budget: BudgetResponse
    quotas: dict[str, QuotaResponse]
    generating: int
    generating_limit: int

    @classmethod
    def from_view(cls, view: NotebookUsageView) -> Self:
        """Build from the use case view."""
        return cls(
            budget=BudgetResponse(
                session=UsagePartResponse.from_view(view.session),
                day=UsagePartResponse.from_view(view.day),
            ),
            quotas={
                name: QuotaResponse(
                    used=quota.used, limit=quota.limit, resets_at=quota.resets_at
                )
                for name, quota in view.quotas.items()
            },
            generating=view.generating,
            generating_limit=view.generating_limit,
        )


# The inputs the notebook chat model reads; `get_notebooks` sets it for the request.
CHAT_MODALITIES: ContextVar[tuple[str, ...] | None] = ContextVar(
    "notebook_chat_modalities", default=None
)


class SourceItemResponse(BaseModel):
    """`SourceItem`."""

    model_config = ConfigDict(use_enum_values=False)

    id: UUID
    notebook_id: UUID
    kind: SourceKind
    title: str
    status: SourceStatus
    failure: SourceFailure | None
    selected: bool
    position: int
    word_count: int
    passage_count: int
    origin: dict[str, Any] | None
    ref: dict[str, Any]
    stale: bool
    has_guide: bool
    synced_at: datetime | None
    created_at: datetime
    label_ids: list[UUID]
    modality: str
    ai_unsupported: bool
    """True when the chat model does not read this input kind: it is kept in the
    notebook but never sent to the model."""

    @classmethod
    def from_entity(cls, source: Source) -> Self:
        """Build from the source entity."""
        modalities = CHAT_MODALITIES.get()
        return cls(
            modality=source_modality(source),
            ai_unsupported=modalities is not None
            and not readable_by(source, modalities),
            id=source.id,
            notebook_id=source.notebook_id,
            kind=source.kind,
            title=source.title,
            status=source.status,
            failure=source.failure,
            selected=source.selected,
            position=source.position,
            word_count=source.word_count,
            passage_count=source.passage_count,
            origin=source.origin,
            ref=source.ref,
            stale=source.status is SourceStatus.STALE,
            has_guide=source.guide is not None,
            synced_at=source.text_synced_at,
            created_at=source.created_at,
            label_ids=source.label_ids,
        )
