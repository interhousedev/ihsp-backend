"""LIB-13, LIB-14: auto-hold, upload windows and school-day waiting (pure rules)."""

import datetime as dt
from uuid import UUID

from app.modules.library.domain.entities import BookDetails
from app.modules.library.domain.enums import ReportReason, Rights, UploaderRole
from app.modules.library.domain.moderation_rules import (
    ReportSignal,
    UploadLimits,
    is_overdue,
    needs_rights_attention,
    school_time_waited,
    should_auto_hold,
    top_reason,
    upload_windows,
    window_resets_at,
)
from app.shared.clock import TASHKENT
from app.shared.ids import new_id

import pytest

SERIOUS = [
    ReportReason.COPYRIGHT,
    ReportReason.PERSONAL_DATA,
    ReportReason.INAPPROPRIATE,
    ReportReason.EXAM_LEAK,
]
MILD = [ReportReason.WRONG_CONTENT, ReportReason.SPAM, ReportReason.OTHER]


def signal(
    reason: ReportReason = ReportReason.COPYRIGHT,
    role: UploaderRole = UploaderRole.STUDENT,
    *,
    reporter: UUID | None = None,
) -> ReportSignal:
    """A report from a new student unless a reporter id is given."""
    return ReportSignal(
        reporter_id=reporter or new_id(), reporter_role=role, reason=reason
    )


# - - - Auto-hold - - -


def test_one_student_report_does_not_hold() -> None:
    """LIB-14: a single student report only enters the queue."""
    assert should_auto_hold([signal()], threshold=2) is False


@pytest.mark.parametrize("first", SERIOUS)
@pytest.mark.parametrize("second", SERIOUS)
def test_two_students_with_serious_reasons_hold(
    first: ReportReason, second: ReportReason
) -> None:
    """LIB-14: two different reporters of a serious kind hold the item."""
    assert should_auto_hold([signal(first), signal(second)], threshold=2) is True


@pytest.mark.parametrize("mild", MILD)
def test_mild_reasons_never_count_towards_the_threshold(mild: ReportReason) -> None:
    """LIB-14: spam, wrong content and other are not serious kinds."""
    reports = [signal(mild), signal(mild), signal(mild)]

    assert should_auto_hold(reports, threshold=2) is False


def test_the_same_reporter_twice_counts_once() -> None:
    """LIB-14: two reasons from one person are still one reporter."""
    me = new_id()
    reports = [
        signal(ReportReason.COPYRIGHT, reporter=me),
        signal(ReportReason.EXAM_LEAK, reporter=me),
    ]

    assert should_auto_hold(reports, threshold=2) is False


@pytest.mark.parametrize(
    "role", [UploaderRole.TEACHER, UploaderRole.LIBRARIAN, UploaderRole.ADMIN]
)
@pytest.mark.parametrize("reason", list(ReportReason))
def test_one_report_from_staff_holds_at_once(
    role: UploaderRole, reason: ReportReason
) -> None:
    """LIB-14: one report from a teacher, librarian or admin holds the item."""
    assert should_auto_hold([signal(reason, role)], threshold=2) is True


def test_threshold_is_configurable() -> None:
    """LIB-14: LIBRARY__AUTO_HOLD_REPORTERS decides how many reporters hold."""
    reports = [signal(), signal(), signal()]

    assert should_auto_hold(reports[:2], threshold=3) is False
    assert should_auto_hold(reports, threshold=3) is True


def test_no_reports_hold_nothing() -> None:
    """LIB-14: an item without open reports is never held."""
    assert should_auto_hold([], threshold=2) is False


def test_top_reason_is_the_most_common_one() -> None:
    """LIB-14: the reason shown to the owner when a report is upheld."""
    reasons = [ReportReason.SPAM, ReportReason.COPYRIGHT, ReportReason.COPYRIGHT]

    assert top_reason(reasons) is ReportReason.COPYRIGHT


def test_top_reason_prefers_the_earlier_report_on_a_tie() -> None:
    """LIB-14: ties go to the reason reported first."""
    assert top_reason([ReportReason.SPAM, ReportReason.COPYRIGHT]) is ReportReason.SPAM


def test_top_reason_of_nothing_is_none() -> None:
    """LIB-14: no reports, no reason."""
    assert top_reason([]) is None


# - - - Upload windows - - -

LIMITS = UploadLimits(student_day=10, student_week=40, teacher_day=30)


def test_students_have_a_day_and_a_week_window() -> None:
    """LIB-13: 10 a day and 40 a week."""
    windows = upload_windows(UploaderRole.STUDENT, LIMITS)

    assert [(w.name, w.limit, w.span) for w in windows] == [
        ("day", 10, dt.timedelta(days=1)),
        ("week", 40, dt.timedelta(days=7)),
    ]


def test_teachers_have_only_a_day_window() -> None:
    """LIB-13: teachers 30 a day."""
    windows = upload_windows(UploaderRole.TEACHER, LIMITS)

    assert [(w.name, w.limit) for w in windows] == [("day", 30)]


@pytest.mark.parametrize("role", [UploaderRole.LIBRARIAN, UploaderRole.ADMIN])
def test_librarians_and_admins_have_no_upload_limit(role: UploaderRole) -> None:
    """LIB-13: staff who run the library are not rate limited."""
    assert upload_windows(role, LIMITS) == ()


def test_window_has_room_below_the_limit() -> None:
    """LIB-13: fewer uploads than the limit means no wait."""
    day, _week = upload_windows(UploaderRole.STUDENT, LIMITS)
    now = dt.datetime(2026, 10, 6, 9, 0, tzinfo=dt.UTC)

    assert window_resets_at(day, [now] * 9) is None


def test_window_reopens_when_the_oldest_upload_ages_out() -> None:
    """LIB-13: at the limit the next upload is possible a day after the oldest."""
    day, _week = upload_windows(UploaderRole.STUDENT, LIMITS)
    start = dt.datetime(2026, 10, 6, 1, 0, tzinfo=dt.UTC)
    times = [start + dt.timedelta(hours=i) for i in range(10)]

    assert window_resets_at(day, list(reversed(times))) == start + dt.timedelta(days=1)


def test_window_over_the_limit_waits_for_enough_uploads_to_age_out() -> None:
    """LIB-13: with 12 uploads and a limit of 10 three must age out."""
    day, _week = upload_windows(UploaderRole.STUDENT, LIMITS)
    start = dt.datetime(2026, 10, 6, 1, 0, tzinfo=dt.UTC)
    times = [start + dt.timedelta(hours=i) for i in range(12)]

    assert window_resets_at(day, times) == times[2] + dt.timedelta(days=1)


# - - - School days (Mon to Fri) - - -


def local(day: int, hour: int) -> dt.datetime:
    """October 2026 in Tashkent."""
    return dt.datetime(2026, 10, day, hour, 0, tzinfo=TASHKENT)


def test_waiting_on_school_days_is_plain_elapsed_time() -> None:
    """LIB-14: Monday 10:00 to Wednesday 10:00 is 48 hours."""
    assert school_time_waited(local(5, 10), local(7, 10)) == dt.timedelta(hours=48)


def test_saturdays_and_sundays_do_not_count() -> None:
    """LIB-14: Friday noon to Monday noon skips the Saturday and the Sunday."""
    assert school_time_waited(local(2, 12), local(5, 12)) == dt.timedelta(hours=24)


def test_a_wait_inside_a_saturday_or_sunday_is_zero() -> None:
    """LIB-14: nothing waits on a Saturday or a Sunday."""
    assert school_time_waited(local(3, 8), local(3, 20)) == dt.timedelta(0)
    assert school_time_waited(local(4, 8), local(4, 20)) == dt.timedelta(0)
    assert school_time_waited(local(3, 8), local(4, 20)) == dt.timedelta(0)


def test_time_runs_backwards_to_zero() -> None:
    """LIB-14: an end before the start is no wait."""
    assert school_time_waited(local(7, 10), local(5, 10)) == dt.timedelta(0)


def test_overdue_needs_more_than_the_sla() -> None:
    """LIB-14: exactly two school days is not yet overdue, a minute more is."""
    start = local(5, 10)

    assert is_overdue(start, local(7, 10), sla_school_days=2) is False
    assert is_overdue(start, local(7, 10) + dt.timedelta(minutes=1), 2) is True


def test_a_weekend_does_not_make_a_friday_upload_overdue() -> None:
    """LIB-14: Friday 15:00 is still fresh on Monday 09:00 (the weekend is skipped)."""
    assert is_overdue(local(2, 15), local(5, 9), sla_school_days=2) is False


def test_a_friday_upload_is_overdue_two_school_days_after_the_weekend() -> None:
    """LIB-14: Friday 15:00 is exactly 48 school hours old on Tuesday 15:00."""
    assert is_overdue(local(2, 15), local(6, 15), sla_school_days=2) is False
    assert is_overdue(local(2, 15), local(6, 16), sla_school_days=2) is True


# - - - Rights that need a look - - -


def book(rights: Rights, checked: bool = True, **basis: str) -> BookDetails:
    """A book's rights data; `basis` keys go into `rights_basis`."""
    return BookDetails(
        rights=rights,
        rights_basis=dict(basis),
        rights_checked_at=dt.datetime(2026, 1, 1, tzinfo=dt.UTC) if checked else None,
    )


NOW = dt.datetime(2026, 10, 6, 9, 0, tzinfo=dt.UTC)


def test_an_unchecked_basis_needs_attention() -> None:
    """LIB-3: a live book whose rights nobody checked."""
    assert needs_rights_attention(book(Rights.OFFICIAL, checked=False), NOW) is True


def test_a_checked_book_without_expiry_is_fine() -> None:
    """LIB-3: public domain, open licence and official books do not expire."""
    for rights in (Rights.PUBLIC_DOMAIN, Rights.OPEN_LICENSE, Rights.OFFICIAL):
        assert needs_rights_attention(book(rights), NOW) is False


@pytest.mark.parametrize(
    ("expires", "expected"),
    [
        ("2026-10-05", True),  # already expired
        ("2026-10-06", True),
        ("2026-12-05", True),  # exactly 60 days ahead
        ("2026-12-06", False),  # 61 days ahead
        ("2027-06-01", False),
    ],
)
def test_a_permission_is_flagged_60_days_before_it_expires(
    expires: str, expected: bool
) -> None:
    """LIB-3: the librarians get a reminder two months ahead."""
    basis = book(Rights.PERMISSION, permission_expires_on=expires)

    assert needs_rights_attention(basis, NOW) is expected


def test_the_expiry_may_also_be_stored_as_expires_on() -> None:
    """LIB-3: both spellings of the key are read."""
    assert needs_rights_attention(book(Rights.PERMISSION, expires_on="2026-11-01"), NOW)


@pytest.mark.parametrize("garbage", ["", "soon", "2026-13-40"])
def test_an_unreadable_or_missing_expiry_is_ignored(garbage: str) -> None:
    """LIB-3: a permission without a readable date cannot be timed."""
    assert not needs_rights_attention(
        book(Rights.PERMISSION, permission_expires_on=garbage), NOW
    )
    assert not needs_rights_attention(book(Rights.PERMISSION), NOW)
