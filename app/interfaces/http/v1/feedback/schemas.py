"""Request and response bodies of the feedback routes (user and admin)."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from app.modules.feedback.application.views import (
    AttachmentView,
    FeedbackView,
    ResponseView,
)
from app.modules.feedback.domain.feedback import (
    MAX_ATTACHMENTS,
    MAX_DESCRIPTION,
    MAX_PAGE_URL,
    MAX_RESPONSE,
    MAX_TITLE,
)
from app.modules.feedback.ports.people import Person

from pydantic import BaseModel, Field

FeedbackKindValue = Literal["idea", "bug", "other"]
FeedbackAreaValue = Literal[
    "id", "my", "staff", "admin", "lms", "library", "share", "bot", "ai",
    "notebooks", "mail", "other",
]  # fmt: skip
FeedbackStatusValue = Literal["new", "in_review", "planned", "done", "rejected"]
FeedbackSourceValue = Literal["web", "bot"]
ChannelValue = Literal["telegram", "mail"]
DeliveryStatusValue = Literal["sent", "failed", "unavailable"]


class FeedbackIn(BaseModel):
    """Body of POST /v1/feedback."""

    kind: FeedbackKindValue
    area: FeedbackAreaValue
    title: str = Field(min_length=1, max_length=MAX_TITLE)
    description: str = Field(min_length=1, max_length=MAX_DESCRIPTION)
    attachment_file_ids: list[UUID] = Field(
        default_factory=list, max_length=MAX_ATTACHMENTS
    )
    page_url: str | None = Field(default=None, max_length=MAX_PAGE_URL)


class FeedbackStatusIn(BaseModel):
    """Body of PATCH /v1/admin/feedback/{id}."""

    status: FeedbackStatusValue


class ResponseIn(BaseModel):
    """Body of POST /v1/admin/feedback/{id}/responses."""

    text: str = Field(min_length=1, max_length=MAX_RESPONSE)
    attachment_file_ids: list[UUID] = Field(
        default_factory=list, max_length=MAX_ATTACHMENTS
    )
    channels: list[ChannelValue] = Field(min_length=1)


class AttachmentOut(BaseModel):
    """An attached file; ``download_url`` is presigned and valid for one hour."""

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


class DeliveryOut(BaseModel):
    """The outcome of one channel of a response."""

    channel: ChannelValue
    status: DeliveryStatusValue


class ResponseOut(BaseModel):
    """An administrator's response."""

    id: UUID
    text: str
    attachments: list[AttachmentOut]
    channels: list[ChannelValue]
    deliveries: list[DeliveryOut]
    author_name: str
    created_at: datetime

    @classmethod
    def of(cls, view: ResponseView) -> "ResponseOut":
        """Map the view."""
        return cls(
            id=view.id,
            text=view.text,
            attachments=[AttachmentOut.of(a) for a in view.attachments],
            channels=view.channels,
            deliveries=[
                DeliveryOut(
                    channel=d.channel.value,
                    status=d.status.value,
                )
                for d in view.deliveries
            ],
            author_name=view.author_name,
            created_at=view.created_at,
        )


class FeedbackOut(BaseModel):
    """A feedback item as its reporter sees it."""

    id: UUID
    kind: FeedbackKindValue
    area: FeedbackAreaValue
    title: str
    description: str
    status: FeedbackStatusValue
    source: FeedbackSourceValue
    created_at: datetime
    attachments: list[AttachmentOut]
    response_count: int

    @classmethod
    def fields_of(cls, view: FeedbackView) -> dict[str, object]:
        """The common fields of every feedback body."""
        item = view.item
        return {
            "id": item.id,
            "kind": item.kind.value,
            "area": item.area.value,
            "title": item.title,
            "description": item.description,
            "status": item.status.value,
            "source": item.source.value,
            "created_at": item.created_at,
            "attachments": [AttachmentOut.of(a) for a in view.attachments],
            "response_count": item.response_count,
        }

    @classmethod
    def of(cls, view: FeedbackView) -> "FeedbackOut":
        """Map the view."""
        return cls.model_validate(cls.fields_of(view))


class FeedbackDetailOut(FeedbackOut):
    """A feedback item with the administrators' responses."""

    responses: list[ResponseOut]

    @classmethod
    def of(cls, view: FeedbackView) -> "FeedbackDetailOut":
        """Map the view."""
        return cls.model_validate(
            {
                **cls.fields_of(view),
                "responses": [ResponseOut.of(r) for r in view.responses],
            }
        )


class FeedbackListOut(BaseModel):
    """Body of GET /v1/feedback/mine."""

    items: list[FeedbackOut]


class ReporterOut(BaseModel):
    """Who sent the feedback (``group_name`` for students)."""

    user_id: UUID
    display_name: str
    roles: list[str]
    group_name: str | None = None

    @classmethod
    def of(cls, person: Person | None) -> "ReporterOut":
        """Map the person (empty values for a deleted account)."""
        assert person is not None  # the presenter always sets it for admins
        return cls(
            user_id=person.user_id,
            display_name=person.display_name,
            roles=list(person.roles),
            group_name=person.group_name,
        )


class AdminFeedbackListItem(FeedbackOut):
    """A feedback item with its reporter."""

    reporter: ReporterOut

    @classmethod
    def of(cls, view: FeedbackView) -> "AdminFeedbackListItem":
        """Map the view."""
        return cls.model_validate(
            {**cls.fields_of(view), "reporter": ReporterOut.of(view.reporter)}
        )


class AdminFeedbackDetail(AdminFeedbackListItem):
    """A feedback item with its reporter, page URL and responses."""

    page_url: str | None
    responses: list[ResponseOut]

    @classmethod
    def of(cls, view: FeedbackView) -> "AdminFeedbackDetail":
        """Map the view."""
        return cls.model_validate(
            {
                **cls.fields_of(view),
                "reporter": ReporterOut.of(view.reporter),
                "page_url": view.item.page_url,
                "responses": [ResponseOut.of(r) for r in view.responses],
            }
        )


class AdminFeedbackListOut(BaseModel):
    """Body of GET /v1/admin/feedback."""

    items: list[AdminFeedbackListItem]
    next_cursor: str | None
