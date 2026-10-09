"""Rules of reports, upload limits and queue waiting (doc §§ 3.5, 3.6). Pure."""

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any, Literal
from uuid import UUID

from app.modules.library.domain.entities import BookDetails
from app.modules.library.domain.enums import ReportReason, Rights, UploaderRole
from app.shared.clock import TASHKENT, to_local

SERIOUS_REASONS = frozenset(
    {
        ReportReason.COPYRIGHT,
        ReportReason.PERSONAL_DATA,
        ReportReason.INAPPROPRIATE,
        ReportReason.EXAM_LEAK,
    }
)
# One report from these roles holds an item at once; a student's needs company.
STAFF_REPORTERS = frozenset(
    {UploaderRole.TEACHER, UploaderRole.LIBRARIAN, UploaderRole.ADMIN}
)
SUNDAY = 6
DAY = timedelta(days=1)
WEEK = timedelta(days=7)


@dataclass(frozen=True, slots=True)
class ReportSignal:
    """What the auto-hold rule needs to know about one open report."""

    reporter_id: UUID
    reporter_role: UploaderRole
    reason: ReportReason


def should_auto_hold(reports: Sequence[ReportSignal], *, threshold: int) -> bool:
    """True when the open reports hide a published item until a librarian decides.

    One report from a teacher, librarian or admin holds at once. Otherwise
    `threshold` different reporters with a serious reason are needed: the same person
    reporting twice counts once, and spam or a wrong fact never holds on its own.
    """
    if any(report.reporter_role in STAFF_REPORTERS for report in reports):
        return True
    serious = {r.reporter_id for r in reports if r.reason in SERIOUS_REASONS}
    return len(serious) >= threshold


def top_reason(reasons: Sequence[ReportReason]) -> ReportReason | None:
    """The most reported reason; on a tie the one reported first."""
    if not reasons:
        return None
    counts = Counter(reasons)
    best = max(counts.values())
    return next(reason for reason in reasons if counts[reason] == best)


# - - - Upload limits - - -


@dataclass(frozen=True, slots=True)
class UploadLimits:
    """Submissions allowed per window (`LIBRARY__LIMIT_UPLOADS_*`)."""

    student_day: int
    student_week: int
    teacher_day: int


@dataclass(frozen=True, slots=True)
class UploadWindow:
    """At most `limit` submissions in any `span`."""

    name: Literal["day", "week"]
    span: timedelta
    limit: int


def upload_windows(
    role: UploaderRole, limits: UploadLimits
) -> tuple[UploadWindow, ...]:
    """The windows that apply to the role; librarians and admins have none."""
    if role is UploaderRole.STUDENT:
        return (
            UploadWindow("day", DAY, limits.student_day),
            UploadWindow("week", WEEK, limits.student_week),
        )
    if role is UploaderRole.TEACHER:
        return (UploadWindow("day", DAY, limits.teacher_day),)
    return ()


def window_resets_at(
    window: UploadWindow, times: Sequence[datetime]
) -> datetime | None:
    """None while a submission is allowed, else when enough old ones age out.

    `times` are the submissions inside the window, in any order.
    """
    if len(times) < window.limit:
        return None
    ordered = sorted(times)
    return ordered[len(ordered) - window.limit] + window.span


# - - - Waiting in the queue - - -


def school_time_waited(start: datetime, end: datetime) -> timedelta:
    """Time from `start` to `end` without Sundays (school days: Monday to Saturday)."""
    if end <= start:
        return timedelta(0)
    cursor, stop = to_local(start), to_local(end)
    total = timedelta(0)
    while cursor < stop:
        midnight = datetime.combine(cursor.date() + DAY, time.min, tzinfo=TASHKENT)
        segment_end = min(midnight, stop)
        if cursor.weekday() != SUNDAY:
            total += segment_end - cursor
        cursor = segment_end
    return total


def is_overdue(start: datetime, end: datetime, sla_school_days: int) -> bool:
    """True when an item waited more than `sla_school_days` school days."""
    return school_time_waited(start, end) > sla_school_days * DAY


# - - - Rights that need a look - - -

RIGHTS_WINDOW = timedelta(days=60)
EXPIRY_KEYS = ("permission_expires_on", "expires_on")


def permission_expiry(basis: dict[str, Any]) -> date | None:
    """The date a permission ends (ISO text in `rights_basis`), or None."""
    for key in EXPIRY_KEYS:
        value = basis.get(key)
        if isinstance(value, str) and value:
            try:
                return date.fromisoformat(value)
            except ValueError:
                return None
    return None


def permission_ends_soon(book: BookDetails, now: datetime) -> bool:
    """True for a permission that ends within 60 days (or already ended)."""
    if book.rights is not Rights.PERMISSION:
        return False
    expiry = permission_expiry(book.rights_basis)
    return expiry is not None and expiry <= (now + RIGHTS_WINDOW).date()


def needs_rights_attention(book: BookDetails, now: datetime) -> bool:
    """True when nobody checked the basis or a permission ends within 60 days."""
    return book.rights_checked_at is None or permission_ends_soon(book, now)
