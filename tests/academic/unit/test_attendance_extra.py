"""EMIS absences on top of the platform's: each (subject, date) counts once."""

import datetime as dt
from uuid import UUID, uuid4

from app.modules.academic.domain.attendance_extra import (
    EmisAbsentDate,
    emis_extra,
    extras_by_key,
)
from app.modules.academic.domain.attendance_merge import merged_absence_count

DAY = dt.date(2026, 10, 5)
STUDENT, GROUP, SUBJECT = uuid4(), uuid4(), uuid4()


def _row(platform: int, day: dt.date = DAY, subject: UUID = SUBJECT) -> EmisAbsentDate:
    return EmisAbsentDate(STUDENT, GROUP, subject, day, platform)


def test_emis_date_already_on_platform_adds_nothing() -> None:
    assert emis_extra(_row(1)) == 0
    assert emis_extra(_row(2)) == 0


def test_emis_only_date_adds_one() -> None:
    assert emis_extra(_row(0)) == 1


def test_extra_agrees_with_merged_count() -> None:
    key = (SUBJECT, DAY)
    for platform in (0, 1, 3):
        assert platform + emis_extra(_row(platform)) == merged_absence_count(
            [key] * platform, [key]
        )


def test_extras_grouped_per_view() -> None:
    other = uuid4()
    rows = [_row(0), _row(0, dt.date(2026, 10, 6)), _row(1), _row(0, subject=other)]
    assert extras_by_key(rows, "student") == {str(STUDENT): 3}
    assert extras_by_key(rows, "group") == {str(GROUP): 3}
    assert extras_by_key(rows, "subject") == {str(SUBJECT): 2, str(other): 1}
    assert extras_by_key(rows, "day") == {"2026-10-05": 2, "2026-10-06": 1}


def test_lesson_and_teacher_views_get_no_extra() -> None:
    assert extras_by_key([_row(0)], "lesson") == {}
    assert extras_by_key([_row(0)], "teacher") == {}
