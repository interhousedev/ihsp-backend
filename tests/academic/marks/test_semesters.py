"""Semester selection and the dates a semester covers; attendance state."""

import datetime as dt
from uuid import UUID

from app.modules.academic.domain.marks.attendance import attendance_state
from app.modules.academic.domain.marks.names import localized
from app.modules.academic.domain.marks.semesters import (
    resolve_semester,
    semester_window,
)

TERMS = [
    (dt.date(2025, 9, 1), dt.date(2025, 12, 31)),
    (dt.date(2026, 1, 12), dt.date(2026, 5, 31)),
    (dt.date(2026, 9, 1), dt.date(2026, 12, 31)),
]
TODAY = dt.date(2026, 10, 6)


def test_current_semester_maps_to_the_term_holding_today() -> None:
    """Semester 3 is the autumn 2026 term; semester 2 the term before it."""
    assert semester_window(TERMS, 3, 3, TODAY) == TERMS[2]
    assert semester_window(TERMS, 3, 2, TODAY) == TERMS[1]
    assert semester_window(TERMS, 3, 1, TODAY) == TERMS[0]


def test_semester_without_a_term_has_no_window() -> None:
    """A semester before the first stored term, or a future one, is unknown."""
    assert semester_window(TERMS[1:], 3, 1, TODAY) is None
    assert semester_window(TERMS, 3, 4, TODAY) is None
    assert semester_window(TERMS, None, 3, TODAY) is None
    assert semester_window([], 3, 3, TODAY) is None


def test_the_last_started_term_is_current_between_terms() -> None:
    """During the summer break the last term is still the current semester."""
    assert semester_window(TERMS, 3, 3, dt.date(2026, 7, 1)) == TERMS[1]


def test_resolve_semester_prefers_request_then_group_then_data() -> None:
    """Requested, else the group's current, else the latest with results, else 1."""
    assert resolve_semester(2, 3, {1}) == 2
    assert resolve_semester(None, 3, {1}) == 3
    assert resolve_semester(None, None, {1, 2}) == 2
    assert resolve_semester(None, None, set()) == 1


def test_localized_falls_back_through_uz_ru_en() -> None:
    """The caller's locale first, then uz, ru, en."""
    name = {"uz": "Fizika", "ru": "Физика", "en": ""}
    assert localized(name, "en") == "Fizika"
    assert localized(name, "ru") == "Физика"
    assert localized({"uz": "", "ru": "", "en": "Physics"}, "ru") == "Physics"
    assert localized({}, "ru") == ""


def test_attendance_state() -> None:
    """present / absent / excused / not_taken from the lesson's arrays."""
    me, other = UUID(int=1), UUID(int=2)
    assert attendance_state(me, None, None, None) == "not_taken"
    assert attendance_state(me, [other], [], None) == "not_taken"
    assert attendance_state(me, [me, other], [other], None) == "present"
    assert attendance_state(me, [me, other], [me], None) == "absent"
    assert attendance_state(me, [me], [me], {str(me): {"by": "x"}}) == "excused"
