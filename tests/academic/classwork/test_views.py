"""WEB-3, WEB-9, STF-2, STF-4: Today pages and lesson pages."""

import datetime as dt
from uuid import UUID

from app.modules.academic.domain.classwork.errors import (
    LessonNotFoundError,
    NotLessonTeacherError,
)
from app.shared.contracts.academic import LessonRef
from app.shared.ids import new_id
from tests.academic.classwork.conftest import Env
from tests.academic.classwork.world import (
    DAY,
    add_lesson,
    add_mark,
    add_result,
    local,
)

import pytest


async def _today_lessons(env: Env) -> dict[int, UUID]:
    """Done, cancelled, now (14:00), next and later lessons of the day."""
    ids: dict[int, UUID] = {}
    for period in (1, 7, 8, 9):
        ids[period] = await add_lesson(env.maker, env.world, period=period)
    ids[2] = await add_lesson(env.maker, env.world, period=2, status="cancelled")
    return ids


async def test_today_shows_the_timeline_with_now_and_next(env: Env) -> None:
    """UF-WEB-02 1-2: done is dimmed, the current one is highlighted."""
    ids = await _today_lessons(env)
    env.links.add(ids[7], role="material")
    env.links.add(ids[7], role="attachment")

    today = await env.services.student_today.execute(env.student("aziz"))

    assert [(item["period"], item["state"]) for item in today["lessons"]] == [
        (1, "done"),
        (2, "cancelled"),
        (7, "now"),
        (8, "next"),
        (9, "later"),
    ]
    card = today["now_or_next"]
    assert card["id"] == str(ids[7])
    assert card["minutes_left"] == 45
    assert card["materials_count"] == 1
    assert card["subject"]["name"] == "Physics"
    assert card["room"]["name"] == "204"


async def test_before_the_lesson_the_card_counts_minutes_to_the_start(env: Env) -> None:
    """UF-WEB-02: "Physics - in 12 min"."""
    env.clock.set(local(DAY, 13, 48))
    lesson_id = await add_lesson(env.maker, env.world, period=7)

    today = await env.services.student_today.execute(env.student("aziz"))

    assert today["now_or_next"]["id"] == str(lesson_id)
    assert today["now_or_next"]["minutes_left"] == 12


async def test_after_the_last_lesson_the_card_shows_the_next_study_day(
    env: Env,
) -> None:
    """UF-WEB-02 1a: "Tomorrow starts at 08:30 with ..."."""
    env.clock.set(local(DAY, 20))
    await add_lesson(env.maker, env.world, period=1)
    tomorrow = await add_lesson(
        env.maker, env.world, day=DAY + dt.timedelta(days=1), period=1
    )

    today = await env.services.student_today.execute(env.student("aziz"))

    assert today["next_study_day"] == "2026-10-07"
    assert today["now_or_next"]["id"] == str(tomorrow)
    assert today["now_or_next"]["minutes_left"] is None
    assert [item["state"] for item in today["lessons"]] == ["done"]


async def test_after_friday_the_next_study_day_is_monday(env: Env) -> None:
    """Nobody studies on a weekend: Friday evening points at Monday's first lesson."""
    friday = DAY + dt.timedelta(days=3)
    env.clock.set(local(friday, 20))
    await add_lesson(env.maker, env.world, day=friday, period=1)
    await add_lesson(env.maker, env.world, day=friday + dt.timedelta(days=1))
    monday = await add_lesson(
        env.maker, env.world, day=friday + dt.timedelta(days=3), period=1
    )

    today = await env.services.student_today.execute(env.student("aziz"))

    assert (friday.isoweekday(), friday.isoformat()) == (5, "2026-10-09")
    assert today["next_study_day"] == "2026-10-12"
    assert today["now_or_next"]["id"] == str(monday)


async def test_on_a_saturday_there_is_no_lesson_today_and_monday_is_next(
    env: Env,
) -> None:
    """A Saturday lesson kept from before is not shown; Monday comes next."""
    saturday = DAY + dt.timedelta(days=4)
    env.clock.set(local(saturday, 10))
    await add_lesson(env.maker, env.world, day=saturday, period=1)
    monday = await add_lesson(
        env.maker, env.world, day=saturday + dt.timedelta(days=2), period=1
    )

    today = await env.services.student_today.execute(env.student("aziz"))

    assert saturday.isoweekday() == 6
    assert today["lessons"] == []
    assert today["next_study_day"] == "2026-10-12"
    assert today["now_or_next"]["id"] == str(monday)


async def test_holiday_shows_the_projected_next_study_day(env: Env) -> None:
    """UF-WEB-02 1b: beyond the generated lessons the schedule projects them."""
    projected = LessonRef(
        id=new_id(),
        date=DAY + dt.timedelta(days=20),
        period=1,
        starts_at=local(DAY + dt.timedelta(days=20), 8, 30),
        ends_at=local(DAY + dt.timedelta(days=20), 9, 15),
        subject_id=env.world.physics_id,
        subject_name="Physics",
        teacher_id=None,
        room_id=None,
        room_slug=None,
        room_name=None,
        audience=(),
        group_names=(),
        status="scheduled",
        topic=None,
        homework_text=None,
        homework_due_date=None,
    )
    env.schedule.projected = [projected]

    today = await env.services.student_today.execute(env.student("aziz"))

    assert today["next_study_day"] == "2026-10-26"
    assert today["now_or_next"] is None


async def test_today_lists_homework_due_next_study_day_and_new_marks(env: Env) -> None:
    """UF-WEB-02 3-4: ticks right there, marks since the last visit."""
    w = env.world
    tomorrow = DAY + dt.timedelta(days=1)
    await add_lesson(env.maker, w, day=tomorrow, period=1)
    given = await add_lesson(
        env.maker,
        w,
        day=DAY - dt.timedelta(days=1),
        homework_text="Solve 5 tasks",
        homework_due_date=tomorrow,
        homework_due_auto=False,
    )
    env.identity.set_preferences(
        w.aziz.id, seen_marks_at=dt.datetime(2026, 10, 6, 6, 0, tzinfo=dt.UTC)
    )
    await add_mark(
        env.maker,
        w.aziz.id,
        w.physics_id,
        value=3,
        created_at=dt.datetime(2026, 10, 6, 5, 0, tzinfo=dt.UTC),
    )
    await add_mark(
        env.maker,
        w.aziz.id,
        w.physics_id,
        value=5,
        day=DAY - dt.timedelta(days=1),
        created_at=dt.datetime(2026, 10, 6, 8, 0, tzinfo=dt.UTC),
    )

    today = await env.services.student_today.execute(env.student("aziz"))

    assert [item["lesson_id"] for item in today["due"]] == [str(given)]
    assert [(m["value"], m["type"]) for m in today["new_marks"]] == [(5, "lesson")]
    assert today["new_marks"][0]["subject"]["short_name"] == "Phys"


async def test_today_semester_card_has_gpa_change_and_absences(env: Env) -> None:
    """UF-WEB-02 5: "4.62, up 0.08 vs last semester" and absences."""
    w = env.world
    await add_result(env.maker, w.aziz.id, 2, 4.62)
    await add_result(env.maker, w.aziz.id, 1, 4.54)
    await add_lesson(
        env.maker,
        w,
        day=DAY - dt.timedelta(days=1),
        attendance_roster=[w.aziz.id, w.bobur.id],
        attendance_absent=[w.aziz.id],
        attendance_version=1,
    )

    today = await env.services.student_today.execute(env.student("aziz"))

    assert today["semester"] == {
        "semester": 2,
        "gpa": 4.62,
        "gpa_change": 0.08,
        "absences": 1,
    }


async def test_today_works_without_any_lessons(env: Env) -> None:
    """UF-WEB-02: nothing scheduled is an empty page, not an error."""
    today = await env.services.student_today.execute(env.student("aziz"))

    assert today["lessons"] == []
    assert today["now_or_next"] is None
    assert today["next_study_day"] is None
    assert today["due"] == []
    assert today["semester"]["gpa"] is None


async def test_lesson_page_has_materials_attachments_homework_mark_and_attendance(
    env: Env,
) -> None:
    """UF-WEB-06: everything about the lesson in one place."""
    w = env.world
    lesson_id = await add_lesson(
        env.maker,
        w,
        homework_text="Read page 5",
        homework_due_date=DAY + dt.timedelta(days=7),
        attendance_roster=[w.aziz.id, w.bobur.id],
        attendance_absent=[w.bobur.id],
        attendance_excused={str(w.bobur.id): {"by": "x", "at": "y", "comment": None}},
        attendance_version=1,
    )
    env.links.add(lesson_id, role="material", title="Lecture 5.pdf")
    env.links.add(
        lesson_id, role="attachment", author_id=w.bobur.id, author_first_name="Bobur"
    )
    env.links.add(lesson_id, role="attachment", author_id=w.camila.id, hidden=True)
    env.links.add(lesson_id, role="attachment", author_id=w.aziz.id, hidden=True)
    await add_mark(env.maker, w.aziz.id, w.physics_id, value=4, lesson_id=lesson_id)

    page = await env.services.student_lesson.execute(lesson_id, env.student("aziz"))

    assert page["lesson"]["id"] == str(lesson_id)
    assert [m["title"] for m in page["materials"]] == ["Lecture 5.pdf"]
    assert len(page["attachments"]) == 2  # Bobur's and their own hidden one
    assert page["attachments"][0]["author"] == {
        "id": str(w.bobur.id),
        "first_name": "Bobur",
        "last_name": "",
    }
    assert page["homework"]["text"] == "Read page 5"
    assert page["my_mark"][0]["value"] == 4
    assert page["my_attendance"] == "present"
    assert page["can_attach"] is True


async def test_lesson_page_shows_each_attendance_state(env: Env) -> None:
    """WEB-9: present, absent, excused, or not taken yet."""
    w = env.world
    taken = await add_lesson(
        env.maker,
        w,
        period=1,
        attendance_roster=[w.aziz.id, w.bobur.id, w.camila.id],
        attendance_absent=[w.bobur.id, w.camila.id],
        attendance_excused={str(w.camila.id): {"by": "x", "at": "y", "comment": None}},
        attendance_version=1,
    )
    open_ = await add_lesson(env.maker, w, period=2)

    async def state(who: str, lesson_id: UUID) -> str:
        page = await env.services.student_lesson.execute(lesson_id, env.student(who))
        return str(page["my_attendance"])

    assert await state("aziz", taken) == "present"
    assert await state("bobur", taken) == "absent"
    assert await state("camila", taken) == "excused"
    assert await state("aziz", open_) == "not_taken"


@pytest.mark.parametrize(
    ("days", "expected"), [(-8, False), (-7, True), (14, True), (15, False)]
)
async def test_students_attach_from_seven_days_back_to_fourteen_ahead(
    env: Env, days: int, expected: bool
) -> None:
    """WEB-10: the attachment window."""
    lesson_id = await add_lesson(
        env.maker, env.world, day=DAY + dt.timedelta(days=days)
    )

    page = await env.services.student_lesson.execute(lesson_id, env.student("aziz"))

    assert page["can_attach"] is expected


async def test_students_outside_the_audience_get_not_found(env: Env) -> None:
    """WEB-9: only students of the audience open the lesson."""
    lesson_id = await add_lesson(
        env.maker, env.world, audience=[f"{env.world.group_id}:1"]
    )

    with pytest.raises(LessonNotFoundError):
        await env.services.student_lesson.execute(lesson_id, env.student("outsider"))
    with pytest.raises(LessonNotFoundError):
        await env.services.student_lesson.execute(lesson_id, env.student("bobur"))


async def test_staff_today_marks_missing_attendance_and_homework(env: Env) -> None:
    """UF-STF-02: badges and the "needs attention" list."""
    w = env.world
    done_no_attendance = await add_lesson(env.maker, w, period=1)
    await add_lesson(
        env.maker, w, period=2, attendance_roster=[w.aziz.id], attendance_absent=[]
    )
    current = await add_lesson(env.maker, w, period=7, homework_text="Task")
    await add_lesson(env.maker, w, period=8)
    yesterday = await add_lesson(env.maker, w, day=DAY - dt.timedelta(days=1))
    await add_lesson(env.maker, w, day=DAY - dt.timedelta(days=8))  # too old
    await add_lesson(env.maker, w, period=3, status="cancelled")

    page = await env.services.staff_today.execute(env.teacher)

    badges = {item["period"]: item for item in page["lessons"]}
    assert badges[1]["attendance_missing"] is True
    assert badges[2]["attendance_missing"] is False
    assert badges[7]["attendance_missing"] is False  # not finished yet
    assert badges[7]["homework_missing"] is False
    assert badges[8]["homework_missing"] is True
    assert badges[3]["homework_missing"] is False  # cancelled
    assert page["now_or_next"]["id"] == str(current)
    attention = [item["id"] for item in page["needs_attention"]]
    assert attention == [str(yesterday), str(done_no_attendance)]


async def test_staff_lesson_has_audience_homework_materials_and_the_sheet(
    env: Env,
) -> None:
    """UF-STF-06, STF-4: the teacher's lesson page."""
    w = env.world
    lesson_id = await add_lesson(
        env.maker,
        w,
        homework_text="Task",
        homework_due_date=DAY,
        homework_due_auto=False,
    )
    env.links.add(lesson_id, role="material")
    env.links.add(
        lesson_id, role="attachment", author_id=w.aziz.id, author_first_name="Aziz"
    )

    page = await env.services.staff_lesson.execute(lesson_id, env.teacher)

    assert page["lesson"]["audience"] == [
        {"group_id": str(w.group_id), "group_name": "2TN2", "subgroup": None}
    ]
    assert page["homework"] == {
        "text": "Task",
        "due_date": "2026-10-06",
        "due_auto": False,
    }
    assert len(page["materials"]) == 1
    assert page["attachments"][0]["author"]["id"] == str(w.aziz.id)
    assert page["attendance"]["submitted"] is False
    assert page["attendance"]["editable"] is True
    assert len(page["attendance"]["roster"]) == 3


async def test_staff_lesson_access_teacher_curator_admin_and_others(env: Env) -> None:
    """STF-4: the teacher or Administration; a curator reads, others are refused."""
    lesson_id = await add_lesson(env.maker, env.world)

    as_admin = await env.services.staff_lesson.execute(lesson_id, env.admin)
    as_curator = await env.services.staff_lesson.execute(lesson_id, env.curator)

    assert as_admin["attendance"]["editable"] is True
    assert as_curator["attendance"]["editable"] is False
    assert len(as_curator["attendance"]["roster"]) == 3
    with pytest.raises(NotLessonTeacherError):
        await env.services.staff_lesson.execute(lesson_id, env.other_teacher)
