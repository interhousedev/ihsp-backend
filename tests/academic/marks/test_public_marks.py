"""The MarksQueries contract other modules use."""

import datetime as dt
from uuid import UUID

from app.modules.academic.wiring_marks import MarksServices
from tests.academic.marks.conftest import OTHER_DAY, Env
from tests.academic.marks.world import DAY


async def test_subjects_summary(services: MarksServices, env: Env) -> None:
    """Names in the student's locale, teachers, marks and attendance counts."""
    summaries = await services.queries.subjects_summary(env.world.user_id, None)

    assert [s.name for s in summaries] == ["Fizika", "Mathematics"]
    physics, math = summaries
    assert (physics.semester_mark, physics.absences) == (3.0, 0)
    assert math.subject_id == env.world.math_id
    assert math.semester_mark == 4.5  # lesson 4.0 and midterm 5.0, no final yet
    assert math.emis_rating == 90
    assert (math.absences, math.lessons_with_attendance) == (1, 1)
    assert math.teacher_names == ("Bobur Aliev",)


async def test_marks_can_be_filtered(services: MarksServices, env: Env) -> None:
    """Marks by subject and by date range, newest first."""
    uid, math = env.world.user_id, env.world.math_id

    everything = await services.queries.marks(uid, None, None, None)
    assert len(everything) == 5
    assert everything[0].date == OTHER_DAY

    only_math = await services.queries.marks(uid, math, DAY, DAY)
    assert sorted((m.type, m.value) for m in only_math) == [
        ("lesson", 4),
        ("lesson", 5),
        ("midterm", 5),
    ]
    assert {m.subject_name for m in only_math} == {"Mathematics"}
    assert {m.lesson_id for m in only_math} == {env.world.math_lesson_1}


async def test_results_of_the_current_semester(
    services: MarksServices, env: Env
) -> None:
    """GPA and a row per subject with the averages."""
    results = await services.queries.results(env.world.user_id, None)

    assert results["semester"] == 3
    assert results["gpa"] == 4.0
    rows = {r["name"]: r for r in results["subjects"]}
    assert rows["Mathematics"]["lesson_avg"] == 4.0
    assert rows["Mathematics"]["midterm_avg"] == 5.0
    assert rows["Mathematics"]["final_avg"] is None
    assert rows["Mathematics"]["marks_count"] == 4
    assert (await services.queries.results(UUID(int=5), 3))["subjects"] == []


async def test_new_marks_since(services: MarksServices, env: Env) -> None:
    """Marks first seen after a moment; the limit keeps the newest."""
    uid = env.world.user_id
    long_ago = dt.datetime.now(dt.UTC) - dt.timedelta(days=1)
    tomorrow = dt.datetime.now(dt.UTC) + dt.timedelta(days=1)

    assert len(await services.queries.new_marks_since(uid, long_ago, 20)) == 5
    assert len(await services.queries.new_marks_since(uid, None, 2)) == 2
    assert await services.queries.new_marks_since(uid, tomorrow, 20) == []


async def test_gpa_for_users(services: MarksServices, env: Env) -> None:
    """A GPA per user, None for a user without results."""
    stranger = UUID(int=5)

    gpa = await services.queries.gpa_for_users([env.world.user_id, stranger], None)

    assert gpa == {env.world.user_id: 4.0, stranger: None}
    assert (await services.queries.gpa_for_users([env.world.user_id], 1)) == {
        env.world.user_id: None
    }
