"""Club <-> LMS course link with two-party consent."""

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID, uuid4

from app.modules.activities.domain.errors import Conflict, Denied

__all__ = [
    "ClubCourseLink",
    "CourseLinkDeniedError",
    "CourseLinkExistsError",
    "CourseLinkStateError",
    "confirm",
    "request_link",
    "unlink",
]


class CourseLinkDeniedError(Denied):
    """The person holds no (or the wrong) side of this link."""


class CourseLinkExistsError(Conflict):
    """The pair is already pending or active."""


class CourseLinkStateError(Conflict):
    """The link is not pending."""


@dataclass(slots=True)
class ClubCourseLink:
    """A link between a club and a course."""

    club_id: UUID
    course_id: UUID
    requested_by: UUID
    requested_side: str
    status: str
    requested_at: datetime
    confirmed_by: UUID | None = None
    confirmed_at: datetime | None = None
    id: UUID = field(default_factory=uuid4)


def request_link(
    club_id: UUID,
    course_id: UUID,
    by_user: UUID,
    *,
    is_club_owner: bool,
    is_course_owner_or_teacher: bool,
    existing: list[ClubCourseLink],
    now: datetime,
) -> ClubCourseLink:
    """Ask for a link; one side waits for the other, both sides link at once."""
    if not (is_club_owner or is_course_owner_or_teacher):
        raise CourseLinkDeniedError()
    if any(
        e.club_id == club_id
        and e.course_id == course_id
        and e.status in ("pending", "active")
        for e in existing
    ):
        raise CourseLinkExistsError()
    side = "club" if is_club_owner else "course"
    both = is_club_owner and is_course_owner_or_teacher
    return ClubCourseLink(
        club_id,
        course_id,
        by_user,
        side,
        "active" if both else "pending",
        now,
        by_user if both else None,
        now if both else None,
    )


def confirm(
    link: ClubCourseLink,
    by_user: UUID,
    *,
    is_club_owner: bool,
    is_course_owner_or_teacher: bool,
    now: datetime,
) -> None:
    """The other side accepts a pending request."""
    if link.status != "pending":
        raise CourseLinkStateError()
    holds_other = (
        is_course_owner_or_teacher if link.requested_side == "club" else is_club_owner
    )
    if not holds_other:
        raise CourseLinkDeniedError()
    link.status = "active"
    link.confirmed_by = by_user
    link.confirmed_at = now


def unlink(
    link: ClubCourseLink, *, is_club_owner: bool, is_course_owner_or_teacher: bool
) -> None:
    """Either side ends a pending or active link."""
    if not (is_club_owner or is_course_owner_or_teacher):
        raise CourseLinkDeniedError()
    if link.status not in ("pending", "active"):
        raise CourseLinkStateError()
    link.status = "ended"
