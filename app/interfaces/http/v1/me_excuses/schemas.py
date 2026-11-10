"""Request and response bodies of the excuse routes (student, staff and admin)."""

import datetime as dt
from typing import Literal
from uuid import UUID

from app.modules.academic.application.excuses.views import (
    AttachmentView,
    ExcuseView,
    MessageView,
)
from app.modules.academic.domain.excuses.excuse import (
    COMMENT_MAX,
    MESSAGE_MAX,
    REASON_MAX,
    ExcuseTemplate,
)

from pydantic import BaseModel, Field

ExcuseStatusValue = Literal["pending", "approved", "rejected", "cancelled"]
ExcuseOriginValue = Literal["request", "curator"]
MAX_FILES = 10
MAX_IDS = 200


class ExcuseTemplateOut(BaseModel):
    """A ready reason of the request form."""

    id: UUID
    code: str
    title: dict[str, str]
    requires_document: bool

    @classmethod
    def of(cls, template: ExcuseTemplate) -> "ExcuseTemplateOut":
        """Map the domain template."""
        return cls(
            id=template.id,
            code=template.code,
            title=template.title,
            requires_document=template.requires_document,
        )


class ExcuseTemplateListOut(BaseModel):
    """GET /v1/me/excuse-templates."""

    items: list[ExcuseTemplateOut]


class AttachmentOut(BaseModel):
    """A file of a thread line with a one-hour download URL."""

    file_id: UUID
    name: str
    mime: str
    size: int
    download_url: str

    @classmethod
    def of(cls, view: AttachmentView) -> "AttachmentOut":
        """Map the view."""
        return cls(
            file_id=view.file_id,
            name=view.name,
            mime=view.mime,
            size=view.size,
            download_url=view.download_url,
        )


class ExcuseMessageOut(BaseModel):
    """One line of the thread."""

    id: UUID
    author_id: UUID
    author_name: str
    body: str
    attachments: list[AttachmentOut]
    created_at: dt.datetime

    @classmethod
    def of(cls, view: MessageView) -> "ExcuseMessageOut":
        """Map the view."""
        m = view.message
        return cls(
            id=m.id,
            author_id=m.author_id,
            author_name=view.author_name,
            body=m.body,
            attachments=[AttachmentOut.of(a) for a in view.attachments],
            created_at=m.created_at,
        )


class ExcuseOut(BaseModel):
    """An excuse; ``thread`` is filled on the detail and after a mutation."""

    id: UUID
    student_id: UUID
    student_name: str
    origin: ExcuseOriginValue
    status: ExcuseStatusValue
    template: ExcuseTemplateOut | None
    reason: str
    starts_on: dt.date
    ends_on: dt.date | None
    lesson_ids: list[UUID]
    subject_ids: list[UUID]
    created_by: UUID
    decided_by: UUID | None
    decided_at: dt.datetime | None
    decision_comment: str | None
    created_at: dt.datetime
    updated_at: dt.datetime
    thread: list[ExcuseMessageOut]

    @classmethod
    def of(cls, view: ExcuseView) -> "ExcuseOut":
        """Map the view."""
        e = view.excuse
        return cls(
            id=e.id,
            student_id=e.student_id,
            student_name=view.student_name,
            origin=e.origin.value,
            status=e.status.value,
            template=(ExcuseTemplateOut.of(view.template) if view.template else None),
            reason=e.reason,
            starts_on=e.starts_on,
            ends_on=e.ends_on,
            lesson_ids=list(e.lesson_ids),
            subject_ids=list(e.subject_ids),
            created_by=e.created_by,
            decided_by=e.decided_by,
            decided_at=e.decided_at,
            decision_comment=e.decision_comment,
            created_at=e.created_at,
            updated_at=e.updated_at,
            thread=[ExcuseMessageOut.of(m) for m in view.thread],
        )


class ExcuseListOut(BaseModel):
    """A page of excuses, newest first."""

    items: list[ExcuseOut]
    next_cursor: str | None


class ExcuseRequestIn(BaseModel):
    """Body of POST /v1/me/excuses."""

    template_id: UUID
    reason: str = Field(default="", max_length=REASON_MAX)
    starts_on: dt.date
    ends_on: dt.date | None = None
    lesson_ids: list[UUID] = Field(default_factory=list, max_length=MAX_IDS)
    subject_ids: list[UUID] = Field(default_factory=list, max_length=MAX_IDS)
    file_ids: list[UUID] = Field(default_factory=list, max_length=MAX_FILES)


class ExcuseExclusionIn(BaseModel):
    """Body of POST /v1/staff/excuses; ``starts_on`` defaults to today."""

    student_id: UUID
    template_id: UUID
    reason: str | None = Field(default=None, max_length=REASON_MAX)
    starts_on: dt.date | None = None
    ends_on: dt.date | None = None
    lesson_ids: list[UUID] = Field(default_factory=list, max_length=MAX_IDS)
    subject_ids: list[UUID] = Field(default_factory=list, max_length=MAX_IDS)


class ExcuseMessageIn(BaseModel):
    """Body of POST /v1/*/excuses/{id}/messages."""

    body: str | None = Field(default=None, max_length=MESSAGE_MAX)
    file_ids: list[UUID] = Field(default_factory=list, max_length=MAX_FILES)


class ExcuseDecisionIn(BaseModel):
    """Body of approve, reject and revoke."""

    comment: str | None = Field(default=None, max_length=COMMENT_MAX)


class ExcuseEndIn(BaseModel):
    """Body of PATCH /v1/staff/excuses/{id}."""

    ends_on: dt.date
