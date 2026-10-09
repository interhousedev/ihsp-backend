"""Read models of the materials area; HTTP schemas map them one to one."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from app.modules.library.application.views import ItemCardView
from app.modules.library.domain.enums import ItemStatus, ReportReason

QueueKind = Literal[
    "student_material", "teacher_material", "suggestion", "report", "rights"
]


class QueueTab(StrEnum):
    """The tabs of the librarian queue (doc § 3.6)."""

    REVIEW = "review"
    REPORTS = "reports"
    HELD = "held"
    RIGHTS = "rights"
    SUGGESTIONS = "suggestions"


@dataclass(frozen=True, slots=True)
class Slice[T]:
    """A page of rows and the cursor of the next page."""

    items: list[T]
    next_cursor: str | None = None


@dataclass(frozen=True, slots=True)
class UploadRowView:
    """`UploadRow`: a material of the caller with its status and place in the queue."""

    item: ItemCardView
    status: ItemStatus
    reason: str | None
    review_message: str | None
    queue_position: int | None


@dataclass(frozen=True, slots=True)
class UploaderView:
    """Who uploaded a queued item, as the librarian sees it."""

    name: str
    cohort: str
    role: str


@dataclass(frozen=True, slots=True)
class ReportCountView:
    """How many open reports an item has for one reason (never who filed them)."""

    reason: ReportReason
    count: int


@dataclass(frozen=True, slots=True)
class SuggestionView:
    """A book suggestion with the suggester's display name."""

    id: UUID
    title: str
    url: str | None
    note: str | None
    user_name: str


@dataclass(frozen=True, slots=True)
class QueueRowView:
    """`ManageQueueRow`: one line of the librarian queue."""

    item: ItemCardView
    kind: QueueKind
    findings: tuple[str, ...]
    reports: tuple[ReportCountView, ...]
    submitted_at: datetime
    uploader: UploaderView | None = None
    report_ids: tuple[UUID, ...] | None = None
    suggestion: SuggestionView | None = None
