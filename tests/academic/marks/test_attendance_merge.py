"""EMIS attendance has priority over the rosters; the roster fills the gaps."""

import datetime as dt

from app.modules.academic.domain.marks.attendance_merge import (
    EmisAttendanceReport,
    RosterEntry,
    combined_source,
    merge_attendance,
)
from app.modules.academic.domain.marks.read_models import AttendanceCount

D1, D2, D3 = dt.date(2026, 10, 5), dt.date(2026, 10, 6), dt.date(2026, 10, 7)
ROSTER = [RosterEntry(D1, absent=True), RosterEntry(D2, absent=False, late=True)]


def test_without_emis_the_roster_counts() -> None:
    """No EMIS data: platform values, source platform."""
    assert merge_attendance(ROSTER, None) == AttendanceCount(1, 2, 1, "platform")
    empty = EmisAttendanceReport(frozenset(), None)
    assert merge_attendance(ROSTER, empty).source == "platform"


def test_emis_absence_overrides_a_lesson_and_the_roster_fills_the_rest() -> None:
    """EMIS marks D2 absent (the roster said late); D1 stays from the roster."""
    count = merge_attendance(ROSTER, EmisAttendanceReport(frozenset({D2})))
    assert count == AttendanceCount(2, 2, 0, "mixed")


def test_emis_only_lessons_are_counted() -> None:
    """An EMIS absence on a day without a roster adds a lesson; all from EMIS."""
    count = merge_attendance(
        [RosterEntry(D1, absent=False)], EmisAttendanceReport(frozenset({D1, D3}))
    )
    assert count == AttendanceCount(2, 2, 0, "emis")
    only = merge_attendance([], EmisAttendanceReport(frozenset({D3})))
    assert only == AttendanceCount(1, 1, 0, "emis")


def test_emis_total_replaces_the_absence_count() -> None:
    """A subject total wins; lessons stay at least the roster's."""
    assert merge_attendance(ROSTER, EmisAttendanceReport(None, 0)) == (
        AttendanceCount(0, 2, 1, "mixed")
    )
    assert merge_attendance(ROSTER, EmisAttendanceReport(None, 5)) == (
        AttendanceCount(5, 5, 1, "emis")
    )


def test_within_limits_absent_dates() -> None:
    """Dates outside the window are dropped."""
    report = EmisAttendanceReport(frozenset({D1, D3})).within(D2, None)
    assert report.absent_dates == frozenset({D3})


def test_combined_source() -> None:
    """One source stays; different ones are mixed; nothing is platform."""
    assert combined_source([]) == "platform"
    assert combined_source(["emis", "emis"]) == "emis"
    assert combined_source(["emis", "platform"]) == "mixed"
