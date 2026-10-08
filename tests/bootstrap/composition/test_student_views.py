"""StudentViews over fake academic use cases: every page has the documented shape."""

import datetime as dt
from typing import Any

from app.bootstrap.adapters.composition.student_views import StudentViewsAdapter
from app.interfaces.http.v1.composition.shared_schemas import (
    LessonItemResponse,
    SemesterGradesResponse,
    StudentAttendanceResponse,
    StudentProfileResponse,
)
from app.shared.actor import Role
from app.shared.ids import new_id
from tests.bootstrap.composition.data import (
    NOW,
    lesson_json,
    make_profile_data,
)
from tests.bootstrap.composition.fakes import FakeUseCase

USER = new_id()
START, END = dt.date(2026, 10, 5), dt.date(2026, 10, 11)


def subject_json() -> dict[str, Any]:
    """A `SubjectRef` dict."""
    return {"id": str(new_id()), "name": "Mathematics", "short_name": "Math"}


def adapter(
    profile: Any = None,
    timetable: Any = None,
    grades: Any = None,
    attendance: Any = None,
) -> tuple[StudentViewsAdapter, list[FakeUseCase]]:
    """The adapter over four fakes, returned with them in constructor order."""
    fakes = [FakeUseCase(profile), FakeUseCase(timetable), FakeUseCase(grades)]
    fakes.append(FakeUseCase(attendance))
    return StudentViewsAdapter(*fakes), fakes  # type: ignore[arg-type]


def assert_runs_as_student(fake: FakeUseCase) -> None:
    """The use case ran as the student, with the student role only."""
    actor = fake.calls[0][0][0]
    assert actor.user_id == USER
    assert actor.roles == frozenset({Role.STUDENT})


async def test_profile_nests_the_group_like_the_student_profile_type() -> None:
    """The flat read model becomes `StudentProfile` with `group: {id, name}`."""
    data = make_profile_data(USER)
    views, fakes = adapter(profile=data)

    profile = await views.profile(USER)

    assert_runs_as_student(fakes[0])
    assert profile["group"] == {"id": str(data.group_id), "name": "2TN2"}
    assert "group_id" not in profile and "group_name" not in profile
    assert profile["user_id"] == str(USER)
    assert profile["curator"]["last_name"] == "Aliyeva"
    assert profile["head_student"] is None
    parsed = StudentProfileResponse.model_validate(profile)
    assert parsed.group.name == "2TN2"
    assert parsed.synced_at == NOW


async def test_timetable_passes_the_range_and_returns_lesson_items() -> None:
    """Lessons come through as `LessonItem` dicts."""
    lessons = [lesson_json(period=1), lesson_json(period=2)]
    views, fakes = adapter(timetable=lessons)

    result = await views.timetable(USER, START, END)

    assert_runs_as_student(fakes[1])
    assert fakes[1].calls[0][0][1:] == (START, END)
    assert [r["period"] for r in result] == [1, 2]
    for item in result:
        LessonItemResponse.model_validate(item)


async def test_grades_are_json_with_the_sync_moment_as_text() -> None:
    """`SemesterGrades`: datetimes become ISO text, the rest is unchanged."""
    grades = {
        "semester": 3,
        "gpa": 4.5,
        "synced_at": NOW,
        "rows": [
            {
                "subject": subject_json(),
                "lesson_avg": 4.0,
                "midterm_avg": None,
                "final_avg": None,
                "semester_mark": 4.5,
                "emis_rating": 90,
                "marks_count": 7,
            }
        ],
    }
    views, fakes = adapter(grades=grades)

    result = await views.grades(USER)

    assert_runs_as_student(fakes[2])
    assert fakes[2].calls[0][0][1:] == (None,)
    assert result["synced_at"] == "2026-10-06T09:00:00Z"
    parsed = SemesterGradesResponse.model_validate(result)
    assert parsed.gpa == 4.5
    assert parsed.rows[0].marks_count == 7


async def test_attendance_keeps_the_from_and_to_keys() -> None:
    """`StudentAttendance` is asked for the default (current term) range."""
    attendance = {
        "from": "2026-09-02",
        "to": "2026-12-30",
        "summary": [
            {
                "subject": subject_json(),
                "absences": 2,
                "excused": 1,
                "lessons": 20,
                "rate": 0.1,
            }
        ],
        "days": [{"date": "2026-10-01", "absences": 2}],
        "missed": [{"lesson": lesson_json(), "excused": True}],
        "not_taken": 1,
    }
    views, fakes = adapter(attendance=attendance)

    result = await views.attendance(USER)

    assert_runs_as_student(fakes[3])
    assert fakes[3].calls[0][0][1:] == (None, None)
    assert result["from"] == "2026-09-02" and result["to"] == "2026-12-30"
    parsed = StudentAttendanceResponse.model_validate(result)
    assert parsed.not_taken == 1
    assert parsed.missed[0].excused is True
