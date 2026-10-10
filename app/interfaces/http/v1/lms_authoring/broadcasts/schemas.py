"""Request and response models of course broadcasts."""

from datetime import datetime
from uuid import UUID

from app.modules.notify.domain.course_broadcast import (
    BODY_MAX_LENGTH,
    TITLE_MAX_LENGTH,
    CourseBroadcast,
)

from pydantic import BaseModel, ConfigDict, Field


class CourseBroadcastBody(BaseModel):
    """POST /v1/staff/lms/courses/{id}/broadcasts: the message for the students."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=TITLE_MAX_LENGTH)
    body: str = Field(min_length=1, max_length=BODY_MAX_LENGTH)


class CourseBroadcastResponse(BaseModel):
    """One sent course broadcast."""

    id: UUID
    course_id: UUID
    author_id: UUID
    title: str
    body: str
    created_at: datetime
    recipients: int | None = Field(
        default=None, description="Students notified; only known right after sending."
    )

    @classmethod
    def of(
        cls, broadcast: CourseBroadcast, recipients: int | None = None
    ) -> "CourseBroadcastResponse":
        """Build the response from a stored broadcast."""
        return cls(
            id=broadcast.id,
            course_id=broadcast.course_id,
            author_id=broadcast.author_id,
            title=broadcast.title,
            body=broadcast.body,
            created_at=broadcast.created_at,
            recipients=recipients,
        )
