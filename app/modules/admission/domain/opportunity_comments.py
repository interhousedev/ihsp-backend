"""Comments on opportunities: posting, moderation and reports.

States: `published` -> `hidden` (staff) -> `published` (staff); `published` or
`hidden` -> `deleted` (the author; terminal). Reports are filed on published
comments only and stay `open` until staff resolve or dismiss them.
"""

import dataclasses
import datetime as dt
from dataclasses import dataclass
from typing import Final, Literal, get_args
from uuid import UUID

from app.modules.admission.domain.errors import InvalidTransitionError

CommentStatus = Literal["published", "hidden", "deleted"]
ReportStatus = Literal["open", "resolved", "dismissed"]
COMMENT_STATUSES: Final = get_args(CommentStatus)
REPORT_STATUSES: Final = get_args(ReportStatus)
BODY_MAX: Final = 2000
REASON_MAX: Final = 500


@dataclass(frozen=True, slots=True)
class OppComment:
    """One comment under an opportunity."""

    id: UUID
    opportunity_id: UUID
    author_id: UUID
    body: str
    created_at: dt.datetime
    status: CommentStatus = "published"
    hidden_by: UUID | None = None
    hidden_at: dt.datetime | None = None
    deleted_at: dt.datetime | None = None


@dataclass(frozen=True, slots=True)
class OppCommentReport:
    """A user's report of a comment, waiting in the staff queue."""

    id: UUID
    comment_id: UUID
    reporter_id: UUID
    reason: str
    created_at: dt.datetime
    status: ReportStatus = "open"
    resolved_by: UUID | None = None
    resolved_at: dt.datetime | None = None


def body_problem(body: str) -> bool:
    """Return whether a comment body is empty or too long."""
    text = body.strip()
    return not text or len(text) > BODY_MAX


def hide(comment: OppComment, by: UUID, now: dt.datetime) -> OppComment:
    """Staff hide a published comment."""
    if comment.status != "published":
        raise InvalidTransitionError(params={"status": comment.status})
    return dataclasses.replace(comment, status="hidden", hidden_by=by, hidden_at=now)


def unhide(comment: OppComment) -> OppComment:
    """Staff restore a hidden comment."""
    if comment.status != "hidden":
        raise InvalidTransitionError(params={"status": comment.status})
    return dataclasses.replace(
        comment, status="published", hidden_by=None, hidden_at=None
    )


def delete(comment: OppComment, now: dt.datetime) -> OppComment:
    """The author deletes a published or hidden comment (terminal)."""
    if comment.status == "deleted":
        raise InvalidTransitionError(params={"status": comment.status})
    return dataclasses.replace(comment, status="deleted", deleted_at=now)


def may_report(comment: OppComment, reporter_id: UUID) -> bool:
    """Only published comments of other people can be reported."""
    return comment.status == "published" and comment.author_id != reporter_id


def close_report(
    report: OppCommentReport, status: ReportStatus, by: UUID, now: dt.datetime
) -> OppCommentReport:
    """Resolve or dismiss an open report."""
    if report.status != "open" or status == "open":
        raise InvalidTransitionError(params={"status": report.status})
    return dataclasses.replace(report, status=status, resolved_by=by, resolved_at=now)
