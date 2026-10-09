"""Requests and responses of the librarian and administration endpoints."""

from datetime import datetime
from typing import Self
from uuid import UUID

from app.interfaces.http.v1.library.catalogue.schemas_items import ItemCardSchema
from app.modules.library.application.materials.views import (
    QueueKind,
    QueueRowView,
    QueueTab,
    ReportCountView,
    SuggestionView,
    UploaderView,
)
from app.modules.library.domain.enums import ReportReason, SanctionKind
from app.modules.library.domain.material_flow import ResolveAction
from app.modules.library.domain.moderation_entities import Sanction

from pydantic import BaseModel, Field, SerializerFunctionWrapHandler, model_serializer

# Keys of `ManageQueueRow` that are `key?:` (absent, never `null`).
_OPTIONAL_KEYS = frozenset({"uploader", "report_ids", "suggestion"})


class QueueParams(BaseModel):
    """`GET /manage/library/queue` query string."""

    tab: QueueTab
    cursor: str | None = Field(default=None, max_length=500)
    limit: int = Field(default=20, ge=1, le=100)


class ModerationBody(BaseModel):
    """`POST /manage/library/items/{id}/{action}`: a reason code and a free note."""

    reason: str | None = Field(default=None, max_length=40)
    note: str | None = Field(default=None, max_length=2000)


class ReportResolveBody(BaseModel):
    """`POST /manage/library/reports/{id}/resolve`."""

    action: ResolveAction


class UploaderResponse(BaseModel):
    """Who uploaded the queued item: name, cohort and role."""

    name: str
    cohort: str
    role: str

    @classmethod
    def from_view(cls, view: UploaderView) -> Self:
        """Build from the read model."""
        return cls(name=view.name, cohort=view.cohort, role=view.role)


class ScanResponse(BaseModel):
    """Findings of the scan job."""

    findings: list[str]


class ReportCountResponse(BaseModel):
    """Open reports of one reason (never who filed them)."""

    reason: ReportReason
    count: int

    @classmethod
    def from_view(cls, view: ReportCountView) -> Self:
        """Build from the read model."""
        return cls(reason=view.reason, count=view.count)


class SuggestionResponse(BaseModel):
    """A book suggestion in the queue."""

    id: UUID
    title: str
    url: str | None
    note: str | None
    user_name: str

    @classmethod
    def from_view(cls, view: SuggestionView) -> Self:
        """Build from the read model."""
        return cls(
            id=view.id,
            title=view.title,
            url=view.url,
            note=view.note,
            user_name=view.user_name,
        )


class QueueRowResponse(BaseModel):
    """`ManageQueueRow`: a `QueueRow` plus the ids a row needs to act on."""

    item: ItemCardSchema
    kind: QueueKind
    scan: ScanResponse
    reports: list[ReportCountResponse]
    submitted_at: datetime
    uploader: UploaderResponse | None = None
    report_ids: list[UUID] | None = None
    suggestion: SuggestionResponse | None = None

    @model_serializer(mode="wrap")
    def _drop_absent(self, handler: SerializerFunctionWrapHandler) -> dict[str, object]:
        """Leave out the optional keys that do not apply to this row."""
        data: dict[str, object] = handler(self)
        return {
            k: v for k, v in data.items() if k not in _OPTIONAL_KEYS or v is not None
        }

    @classmethod
    def from_view(cls, view: QueueRowView) -> Self:
        """Build from the read model."""
        return cls(
            item=ItemCardSchema.from_view(view.item),
            kind=view.kind,
            scan=ScanResponse(findings=list(view.findings)),
            reports=[ReportCountResponse.from_view(r) for r in view.reports],
            submitted_at=view.submitted_at,
            uploader=(
                UploaderResponse.from_view(view.uploader) if view.uploader else None
            ),
            report_ids=None if view.report_ids is None else list(view.report_ids),
            suggestion=(
                SuggestionResponse.from_view(view.suggestion)
                if view.suggestion
                else None
            ),
        )


class SanctionBody(BaseModel):
    """`POST /admin/library/sanctions`."""

    user_id: UUID
    kind: SanctionKind
    until: datetime | None = None
    reason: str = Field(min_length=1, max_length=2000)


class SanctionResponse(BaseModel):
    """`Sanction` of the contract."""

    id: UUID
    user_id: UUID
    kind: SanctionKind
    until: datetime | None
    reason: str
    item_id: UUID | None
    created_at: datetime

    @classmethod
    def from_entity(cls, sanction: Sanction) -> Self:
        """Build from the stored sanction."""
        return cls(
            id=sanction.id,
            user_id=sanction.user_id,
            kind=sanction.kind,
            until=sanction.until,
            reason=sanction.reason,
            item_id=sanction.item_id,
            created_at=sanction.created_at,
        )
