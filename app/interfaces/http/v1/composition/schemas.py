"""Response models of the `/v1/me` composition endpoints."""

import datetime as dt
from typing import Any, Literal
from uuid import UUID

from app.interfaces.http.v1.composition.shared_schemas import (
    HomeworkItemResponse,
    LessonItemResponse,
    SubjectRefResponse,
)

from pydantic import BaseModel


class AlertResponse(BaseModel):
    """`Alert`."""

    kind: Literal[
        "emis_reauth",
        "no_subgroup",
        "files_expiring",
        "pending_approvals",
        "sync_failed",
    ]
    # Values for the alert text, e.g. `{count: 2}`; the keys depend on `kind`.
    params: dict[str, Any]
    action_url: str | None


class UsedByResponse(BaseModel):
    """`UsedBy`: where a file is used."""

    kind: Literal["link", "lesson", "chat"]
    id: UUID
    label: str


class FileItemResponse(BaseModel):
    """`FileItem`."""

    id: UUID
    name: str
    content_type: str
    byte_size: int
    purpose: Literal["ai_upload", "link", "mail"]
    status: Literal["pending", "processing", "ready", "rejected", "deleted"]
    reject_reason: str | None
    text_bytes: int | None
    assistant_ready: bool
    created_at: dt.datetime
    expires_on: dt.date | None
    used_by: list[UsedByResponse]


class FlashcardSetItemResponse(BaseModel):
    """`FlashcardSetItem`."""

    id: UUID
    title: str
    description: str | None
    source: Literal["manual", "ai", "mcp", "copied"]
    card_count: int
    due_today: int
    new_today: int


class SearchResultsResponse(BaseModel):
    """`SearchResults`: at most five items per group."""

    subjects: list[SubjectRefResponse]
    lessons: list[LessonItemResponse]
    homework: list[HomeworkItemResponse]
    files: list[FileItemResponse]
    flashcard_sets: list[FlashcardSetItemResponse]


class CalendarTokenResponse(BaseModel):
    """The secret feed URL; shown once."""

    url: str
