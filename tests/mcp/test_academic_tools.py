"""A1, A5, B2: sync refresh, teachers, GPA, marks by subject and lesson detail."""

from datetime import date, timedelta
from typing import Any
from uuid import uuid4

from app.shared.contracts.academic import MarkRef
from tests.mcp.conftest import World
from tests.mcp.fakes import SUBJECT_ID, make_lesson
from tests.mcp.helpers import call, data_of


def _mark(subject_id: Any, semester: int, day: date, value: int = 5) -> MarkRef:
    return MarkRef(
        subject_id=subject_id,
        subject_name=f"S{str(subject_id)[:4]}",
        semester=semester,
        type="lesson",
        value=value,
        date=day,
        lesson_id=None,
    )


async def _one(world: World, scope: str, tool: str, **arguments: Any) -> Any:
    token, actor = world.connector_token("student", scope)
    async with world.session("student", token) as session:
        return await call(session, tool, **arguments), actor


async def test_refresh_passes_through_the_actor(world: World) -> None:
    """A1: the sync is the caller's own and links back to settings."""
    world.academic_tools.refresh_answer = {"status": "cooldown", "retry_after": 60}
    result, actor = await _one(world, "sync:run", "refresh_my_marks")

    data = data_of(result)
    assert data["status"] == "cooldown"
    assert data["links"]["open"]
    assert world.academic_tools.calls == [("request_refresh", actor.user_id)]


async def test_sync_status_reads_the_callers_job(world: World) -> None:
    """A1: status of the caller, no arguments."""
    world.academic_tools.status_answer = {"status": "failed", "error": "sync_failed"}
    result, actor = await _one(world, "sync:run", "get_sync_status")

    assert data_of(result)["error"] == "sync_failed"
    assert world.academic_tools.calls == [("sync_status", actor.user_id)]


async def test_my_teachers_have_links(world: World) -> None:
    """A1: a teacher card links to the teacher's page."""
    teacher_id = uuid4()
    world.academic_tools.teachers = [{"id": teacher_id, "first_name": "Ali"}]
    result, _ = await _one(world, "teachers:read", "get_my_teachers")

    [teacher] = data_of(result)["teachers"]
    assert str(teacher_id) in teacher["links"]["open"]


async def test_teacher_timetable_defaults_to_a_week(world: World) -> None:
    """A1: the range is resolved and belongs to the caller."""
    teacher_id = uuid4()
    result, actor = await _one(
        world, "teachers:read", "get_teacher_timetable", teacher_id=str(teacher_id)
    )

    assert data_of(result)["lessons"]
    [(user_id, asked, start, end)] = world.academic_tools.timetable_calls
    assert (user_id, asked) == (actor.user_id, teacher_id)
    assert (end - start).days == 6


async def test_teacher_timetable_refuses_a_long_range(world: World) -> None:
    """A1: the 120-day cap applies."""
    result, _ = await _one(
        world,
        "teachers:read",
        "get_teacher_timetable",
        teacher_id=str(uuid4()),
        date_from="2026-01-01",
        date_to="2026-12-01",
    )
    assert result.isError


async def test_gpa_says_who_calculated_it(world: World) -> None:
    """A5: the GPA is labelled as the platform's, subjects without marks are dropped."""
    world.academic_tools.gpa_answer = {
        "semester": 3,
        "gpa": 4.5,
        "subjects": [
            {"subject_id": str(SUBJECT_ID), "name": "A", "marks_count": 2},
            {"subject_id": str(uuid4()), "name": "B", "marks_count": 0},
        ],
    }
    result, _ = await _one(world, "marks:read", "get_gpa", semester=3)

    data = data_of(result)
    assert data["calculated_by"] == "platform"
    assert [row["name"] for row in data["subjects"]] == ["A"]


async def test_results_drop_subjects_without_marks(
    world: World, monkeypatch: Any
) -> None:
    """A5: get_results shows no empty subject."""

    async def results(user_id: Any, semester: Any) -> dict[str, Any]:
        return {
            "semester": 3,
            "gpa": 4.0,
            "subjects": [
                {"name": "A", "marks_count": 1},
                {"name": "B", "marks_count": 0},
            ],
        }

    monkeypatch.setattr(world.marks, "results", results)
    result, _ = await _one(world, "marks:read", "get_results")
    assert [row["name"] for row in data_of(result)["subjects"]] == ["A"]


async def test_marks_group_by_subject_and_show_only_marks(
    world: World, monkeypatch: Any
) -> None:
    """A5: marks by subject; no entry for anything without a mark."""
    first, second = uuid4(), uuid4()

    async def marks(*_: Any) -> list[MarkRef]:
        return [
            _mark(first, 3, date(2026, 10, 2)),
            _mark(second, 3, date(2026, 10, 1)),
            _mark(first, 3, date(2026, 9, 30), 4),
        ]

    monkeypatch.setattr(world.marks, "marks", marks)
    result, _ = await _one(
        world, "marks:read", "get_marks", date_from="2026-01-01", date_to="2026-12-31"
    )

    subjects = data_of(result)["subjects"]
    assert {s["subject_id"]: len(s["marks"]) for s in subjects} == {
        str(first): 2,
        str(second): 1,
    }


async def test_marks_of_exact_semesters(world: World, monkeypatch: Any) -> None:
    """A5: only those semesters; an unknown one is an empty entry, not an error."""
    subject = uuid4()

    async def marks(*_: Any) -> list[MarkRef]:
        return [
            _mark(subject, 2, date(2026, 3, 2)),
            _mark(subject, 3, date(2026, 10, 1)),
        ]

    monkeypatch.setattr(world.marks, "marks", marks)
    result, _ = await _one(world, "marks:read", "get_marks", semesters=[3, 9])

    rows = data_of(result)["semesters"]
    assert [row["semester"] for row in rows] == [3, 9]
    assert len(rows[0]["subjects"][0]["marks"]) == 1
    assert rows[1]["subjects"] == []


async def test_marks_refuse_dates_with_semesters(world: World) -> None:
    """A5: a date period or semesters, not both."""
    result, _ = await _one(
        world, "marks:read", "get_marks", semesters=[1], date_from="2026-01-01"
    )
    assert result.isError


async def test_marks_range_boundaries(world: World) -> None:
    """A5: up to 366 days here, one more is refused."""
    start = date(2025, 1, 1)
    good, _ = await _one(
        world,
        "marks:read",
        "get_marks",
        date_from=start.isoformat(),
        date_to=(start + timedelta(days=366)).isoformat(),
    )
    bad, _ = await _one(
        world,
        "marks:read",
        "get_marks",
        date_from=start.isoformat(),
        date_to=(start + timedelta(days=367)).isoformat(),
    )
    assert not good.isError
    assert bad.isError


async def test_too_many_semesters_are_refused(world: World) -> None:
    """A5: at most 12 semesters."""
    result, _ = await _one(world, "marks:read", "get_marks", semesters=list(range(13)))
    assert result.isError


async def test_lesson_detail_marks_third_party_text(world: World) -> None:
    """B2: homework and materials are labelled untrusted; the page link is ours."""
    token, actor = world.connector_token("student", "materials:read")
    lesson_id = uuid4()
    world.academic_tools.details[(actor.user_id, lesson_id)] = {
        "lesson": {"id": lesson_id, "topic": "Limits​"},
        "homework": {"text": "Do​ it"},
        "materials": {
            "homework": [],
            "classwork": [{"title": "Slides", "kind": "file"}],
            "video": [],
            "other": [],
        },
        "attachments": [],
        "my_mark": [],
        "my_attendance": "present",
    }

    async with world.session("student", token) as session:
        result = await call(session, "get_lesson_detail", lesson_id=str(lesson_id))

    data = data_of(result)
    assert data["lesson"]["topic"] == "Limits"
    assert data["homework"]["text"] == "Do it"
    assert "materials.classwork[].title" in data["untrusted_fields"]
    assert str(lesson_id) in data["links"]["open"]


async def test_schedule_names_the_teacher(world: World) -> None:
    """A1: a lesson of the schedule carries its teacher's name."""
    token, actor = world.connector_token("student", "schedule:read")
    teacher_id = uuid4()
    lesson = make_lesson(
        id=uuid4(), date=world.clock.now().date(), teacher_id=teacher_id
    )
    world.schedule.lessons[lesson.id] = lesson
    world.schedule.audience.add((actor.user_id, lesson.id))
    world.academic_tools.names[teacher_id] = "Ali Valiyev"

    async with world.session("student", token) as session:
        result = await call(session, "get_schedule")

    assert data_of(result)["lessons"][0]["teacher_name"] == "Ali Valiyev"
