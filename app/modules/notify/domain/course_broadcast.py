"""A message a course admin sent to the students enrolled in the course."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.shared.base_error import ValidationFailedError

TITLE_MAX_LENGTH = 120
BODY_MAX_LENGTH = 2000


class CourseBroadcastInvalidError(ValidationFailedError):
    """The title or the text of a course broadcast is empty or too long."""

    code = "notify/course-broadcast-invalid"
    message_key = "notify-course-broadcast-invalid"


@dataclass(frozen=True, slots=True)
class CourseBroadcast:
    """One sent course broadcast (a row of the history)."""

    id: UUID
    course_id: UUID
    author_id: UUID
    title: str
    body: str
    created_at: datetime


def clean_broadcast_text(title: str, body: str) -> tuple[str, str]:
    """Trim the texts; title 1-120 and body 1-2000 characters, else raise."""
    clean_title, clean_body = title.strip(), body.strip()
    if not 1 <= len(clean_title) <= TITLE_MAX_LENGTH:
        raise CourseBroadcastInvalidError(params={"field": "title"})
    if not 1 <= len(clean_body) <= BODY_MAX_LENGTH:
        raise CourseBroadcastInvalidError(params={"field": "body"})
    return clean_title, clean_body
