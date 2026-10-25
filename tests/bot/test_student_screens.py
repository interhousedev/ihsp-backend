"""UF-BOT-03: Today, Marks and Homework for students; Today for teachers."""

from datetime import timedelta
from typing import Any

from app.shared.contracts.academic import MarkRef
from app.shared.contracts.callbacks import HomeworkDoneCb
from app.shared.ids import new_id, uuid_to_b64
from tests.bot.support.fakes import (
    NOW,
    TEACHER_TG,
    TODAY,
    World,
    make_lesson,
)
from tests.bot.support.harness import Harness


async def test_today_lists_the_students_lessons_with_times_and_rooms(
    harness: Harness,
) -> None:
    """UF-BOT-03 step 2: today's lessons with times (Tashkent) and rooms."""
    lesson = make_lesson(
        starts_at=NOW + timedelta(hours=1), ends_at=NOW + timedelta(hours=2)
    )
    harness.world.schedule.student_lessons = [lesson]

    await harness.send("/today")

    text = harness.last_text()
    assert "bot-today-title[date=06.10]" in text
    assert "15:00–16:00 <b>Physics</b> · Room 102" in text
    assert harness.last_callbacks() == ["m:menu"]


async def test_cancelled_lessons_are_struck_through(harness: Harness) -> None:
    """A cancelled lesson stays visible but marked."""
    harness.world.schedule.student_lessons = [make_lesson(status="cancelled")]

    await harness.send("/today")

    assert "<s>" in harness.last_text()
    assert "bot-lesson-cancelled" in harness.last_text()


async def test_today_without_lessons_says_so(harness: Harness) -> None:
    """No lessons gives a short note."""
    await harness.send("/today")

    assert "bot-today-empty" in harness.last_text()


async def test_teacher_today_marks_attendance_of_finished_lessons(
    harness: Harness,
) -> None:
    """UF-BOT-03 step 2: teachers see attendance state for finished lessons."""
    done = make_lesson(
        subject_name="Math",
        starts_at=NOW - timedelta(hours=3),
        ends_at=NOW - timedelta(hours=2),
    )
    missing = make_lesson(
        subject_name="Chemistry",
        starts_at=NOW - timedelta(hours=2),
        ends_at=NOW - timedelta(hours=1),
    )
    upcoming = make_lesson(
        subject_name="Art",
        starts_at=NOW + timedelta(hours=1),
        ends_at=NOW + timedelta(hours=2),
    )
    harness.world.schedule.teacher_lessons = [upcoming, missing, done]
    harness.world.classwork_queries.missing = [missing]

    await harness.send("/today", user_id=TEACHER_TG)

    lines = harness.last_text().splitlines()
    assert lines[1].endswith("bot-today-attendance-done")
    assert lines[2].endswith("bot-today-attendance-missing")
    assert "attendance" not in lines[3]
    assert "m:lesson" in harness.last_callbacks()


async def test_marks_show_recent_marks_and_semester_results(harness: Harness) -> None:
    """UF-BOT-03 step 3: marks of the last 7 days and the semester marks."""
    world = harness.world
    world.marks.mark_list = [
        MarkRef(
            subject_id=new_id(),
            subject_name="Mathematics",
            semester=1,
            type="lesson",
            value=5,
            date=TODAY,
            lesson_id=None,
        ),
        MarkRef(
            subject_id=new_id(),
            subject_name="Physics",
            semester=1,
            type="midterm",
            value=3,
            date=TODAY - timedelta(days=2),
            lesson_id=None,
        ),
    ]
    world.marks.result = {
        "semester": 1,
        "gpa": 4.55,
        "subjects": [{"name": "Physics", "semester_mark": 3.95}],
    }

    await harness.send("/marks")

    text = harness.last_text()
    assert "Mathematics — <b>5</b> (bot-mark-type-lesson), 06.10" in text
    assert "Physics — <b>3</b> (bot-mark-type-midterm), 04.10" in text
    assert "bot-marks-gpa[gpa=4.55]" in text
    assert "Physics: 3.95" in text
    open_button = harness.last_buttons()[0][0]
    assert open_button.web_app is not None
    assert open_button.web_app.url == "http://localhost:3002/grades/"


async def test_homework_lists_items_with_a_done_button(harness: Harness) -> None:
    """UF-BOT-03 step 4: the Upcoming list; each item has a Done button."""
    lesson = make_lesson(
        subject_name="Chemistry",
        homework_text="Read chapter 4",
        homework_due_date=TODAY + timedelta(days=1),
    )
    harness.world.classwork_queries.items = [
        {"lesson": lesson, "done_at": None, "note": None}
    ]

    await harness.send("/homework")

    assert "Read chapter 4" in harness.last_text()
    assert (
        harness.last_callbacks()[0]
        == HomeworkDoneCb(lesson=uuid_to_b64(lesson.id), done=True).pack()
    )


async def test_homework_past_due_stays_in_the_list_and_is_marked_overdue(
    harness: Harness,
) -> None:
    """WEB-18, UF-BOT-03: past-due homework is not dropped; it says it is overdue."""
    late = make_lesson(
        subject_name="Chemistry",
        date=TODAY - timedelta(days=3),
        homework_text="Learn the table",
        homework_due_date=TODAY - timedelta(days=1),
    )
    undated = make_lesson(
        subject_name="Physics",
        date=TODAY - timedelta(days=2),
        homework_text="Read page 5",
        homework_due_date=None,
    )
    harness.world.classwork_queries.items = [
        {"lesson": late, "done_at": None, "note": None},
        {"lesson": undated, "done_at": None, "note": None},
    ]

    await harness.send("/homework")

    text = harness.last_text()
    assert "bot-homework-item-overdue[due=05.10,subject=Chemistry]" in text
    assert "bot-homework-item[due=04.10,subject=Physics]" in text
    [asked] = harness.world.classwork_queries.homework_starts
    assert asked is not None
    assert asked < TODAY - timedelta(days=30)


async def test_done_button_ticks_the_homework_and_refreshes_the_list(
    harness: Harness, world: World
) -> None:
    """UF-BOT-03 step 4: Done calls set_homework_done and re-reads the list."""
    lesson = make_lesson(homework_text="Read chapter 4")
    item: dict[str, Any] = {"lesson": lesson, "done_at": None, "note": None}
    world.classwork_queries.items = [item]
    done = HomeworkDoneCb(lesson=uuid_to_b64(lesson.id), done=True).pack()

    item["done_at"] = NOW  # classwork stores the tick before the list is re-read
    await harness.press(done)

    assert ("homework_done", (lesson.id, True)) in world.classwork.calls
    assert "bot-homework-empty" in harness.last_text()
