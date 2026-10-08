"""TeacherViews over fake academic use cases."""

import datetime as dt
from typing import Any
from uuid import UUID

from app.bootstrap.adapters.composition.teacher_views import TeacherViewsAdapter
from app.interfaces.http.v1.composition.shared_schemas import (
    GroupItemResponse,
    LessonItemResponse,
)
from app.shared.actor import Role
from app.shared.ids import new_id
from tests.bootstrap.composition.data import lesson_json, make_group_data
from tests.bootstrap.composition.fakes import FakeUseCase

TEACHER = new_id()
START, END = dt.date(2026, 9, 29), dt.date(2026, 10, 6)


def row(teacher_id: UUID, *lessons: dict[str, Any]) -> dict[str, Any]:
    """A row of the `MissingAttendance` use case."""
    return {
        "teacher": {"id": str(teacher_id), "first_name": "Gulnora", "last_name": "K"},
        "lessons": list(lessons),
    }


def adapter(
    timetable: Any = None, missing: Any = None, groups: Any = None
) -> tuple[TeacherViewsAdapter, FakeUseCase, FakeUseCase, FakeUseCase]:
    """The adapter over three fakes."""
    fakes = FakeUseCase(timetable), FakeUseCase(missing), FakeUseCase(groups)
    return TeacherViewsAdapter(*fakes), *fakes  # type: ignore[arg-type]


async def test_timetable_runs_as_the_teacher() -> None:
    """The staff timetable is asked as the teacher and returns `LessonItem`s."""
    views, timetable, _, _ = adapter(timetable=[lesson_json(), lesson_json()])

    result = await views.timetable(TEACHER, START, END)

    actor = timetable.calls[0][0][0]
    assert actor.user_id == TEACHER
    assert actor.roles == frozenset({Role.TEACHER})
    assert timetable.calls[0][0][1:] == (START, END)
    assert len(result) == 2
    for item in result:
        LessonItemResponse.model_validate(item)


async def test_missing_attendance_picks_the_teachers_row_out_of_all_rows() -> None:
    """The use case reports every teacher: only this teacher's lessons come back."""
    mine = lesson_json(topic="Limits")
    other = lesson_json(topic="Other teacher")
    rows = [row(new_id(), other), row(TEACHER, mine)]
    views, _, missing, _ = adapter(missing=rows)

    result = await views.missing_attendance(TEACHER, START, END)

    assert [item["topic"] for item in result] == ["Limits"]
    LessonItemResponse.model_validate(result[0])
    actor = missing.calls[0][0][0]
    assert actor.user_id == TEACHER
    assert actor.roles == frozenset({Role.ADMIN})
    assert missing.calls[0][0][1:] == (START, END)


async def test_missing_attendance_is_empty_when_the_teacher_has_no_row() -> None:
    """Nothing missing for this teacher: an empty list, not an error."""
    views, _, _, _ = adapter(missing=[row(new_id(), lesson_json())])

    assert await views.missing_attendance(TEACHER, START, END) == []


async def test_curated_groups_are_group_items() -> None:
    """The read models become `GroupItem` dicts with the curator nested."""
    groups = [make_group_data("2TN2"), make_group_data("1TN1")]
    views, _, _, curated = adapter(groups=groups)

    result = await views.curated_groups(TEACHER)

    actor = curated.calls[0][0][0]
    assert actor.user_id == TEACHER and actor.roles == frozenset({Role.TEACHER})
    assert [item["name"] for item in result] == ["2TN2", "1TN1"]
    assert result[0]["id"] == str(groups[0].id)
    assert result[0]["curator"]["first_name"] == "Nodira"
    assert result[0]["head_student"] is None
    for item in result:
        GroupItemResponse.model_validate(item)
