"""UF-BOT-03 step 5: the Current lesson screen of a teacher."""

from datetime import timedelta

from app.shared.contracts.callbacks import (
    AttActionCb,
    HomeworkPromptCb,
    ResourceLessonCb,
)
from app.shared.ids import uuid_to_b64
from tests.bot.support.fakes import NOW, STUDENT_TG, TEACHER_TG, make_lesson
from tests.bot.support.harness import Harness


async def test_current_lesson_offers_attendance_homework_and_resources(
    harness: Harness,
) -> None:
    """BOT-9: the screen has Attendance, Homework and Add resource."""
    lesson = make_lesson()
    harness.world.schedule.teacher_lessons = [lesson]
    encoded = uuid_to_b64(lesson.id)

    await harness.press("m:lesson", user_id=TEACHER_TG)

    assert harness.last_text().splitlines()[0] == "<b>bot-lesson-current</b>"
    assert harness.last_callbacks() == [
        AttActionCb(lesson=encoded, action="edit").pack(),
        HomeworkPromptCb(lesson=encoded, action="add").pack(),
        ResourceLessonCb(lesson=encoded, role="p").pack(),
        "m:menu",
    ]


async def test_the_next_lesson_is_shown_when_none_is_running(harness: Harness) -> None:
    """The current or the next lesson, skipping finished and cancelled ones."""
    finished = make_lesson(
        subject_name="Done",
        starts_at=NOW - timedelta(hours=3),
        ends_at=NOW - timedelta(hours=2),
    )
    cancelled = make_lesson(
        subject_name="Gone",
        status="cancelled",
        starts_at=NOW + timedelta(hours=1),
        ends_at=NOW + timedelta(hours=2),
    )
    later = make_lesson(
        subject_name="Later",
        starts_at=NOW + timedelta(hours=3),
        ends_at=NOW + timedelta(hours=4),
    )
    harness.world.schedule.teacher_lessons = [later, cancelled, finished]

    await harness.press("m:lesson", user_id=TEACHER_TG)

    assert "bot-lesson-next" in harness.last_text()
    assert "Later" in harness.last_text()


async def test_no_lessons_ahead_says_so(harness: Harness) -> None:
    """Nothing in the coming days gives a note."""
    await harness.press("m:lesson", user_id=TEACHER_TG)

    assert harness.last_text() == "bot-lesson-none"


async def test_attendance_button_opens_the_checklist(harness: Harness) -> None:
    """The Attendance button shows the roster of the lesson."""
    lesson = harness.world.classwork.state["lesson"]
    harness.world.schedule.teacher_lessons = [lesson]
    encoded = uuid_to_b64(lesson.id)

    await harness.press(
        AttActionCb(lesson=encoded, action="edit").pack(), user_id=TEACHER_TG
    )

    assert "Alice" in harness.last_labels()


async def test_students_do_not_get_the_teacher_screen(harness: Harness) -> None:
    """The Current lesson screen is for teachers only."""
    await harness.press("m:lesson", user_id=STUDENT_TG)

    assert harness.toasts[-1].text == "bot-stale-button"
