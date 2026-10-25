"""TMP-1: the Journal button of the lesson prompt puts temporary marks."""

from uuid import UUID

from app.interfaces.bot.callbacks import JournalCb, JournalMarkCb, JournalStudentCb
from app.shared.base_error import ForbiddenError
from app.shared.contracts.callbacks import AttActionCb
from app.shared.ids import uuid_to_b64
from tests.bot.support.fakes import TEACHER_TG, World
from tests.bot.support.harness import Harness


class NotLessonTeacherError(ForbiddenError):
    """Same code and key as the classwork module's error."""

    code = "academic/not-lesson-teacher"
    message_key = "academic-not-lesson-teacher"


def lesson(world: World) -> str:
    """The packed id of the prompt's lesson."""
    return uuid_to_b64(world.classwork.state["lesson"].id)


def student_id(world: World, pos: int) -> UUID:
    """The user id of the roster student at the position."""
    user_id: UUID = world.classwork.state["roster"][pos]["user_id"]
    return user_id


def journal(world: World, action: str = "open") -> str:
    """Callback data of the Journal or Back button."""
    return JournalCb(lesson=lesson(world), action=action).pack()


def student(world: World, pos: int) -> str:
    """Callback data of a student button in the journal."""
    return JournalStudentCb(lesson=lesson(world), pos=pos).pack()


def mark(world: World, pos: int, value: int) -> str:
    """Callback data of a mark button."""
    return JournalMarkCb(lesson=lesson(world), pos=pos, value=value).pack()


async def test_checklist_and_summary_have_a_journal_button(harness: Harness) -> None:
    """The prompt offers Journal before and after attendance is submitted."""
    world = harness.world
    edit = AttActionCb(lesson=lesson(world), action="edit").pack()
    await harness.press(edit, user_id=TEACHER_TG)
    assert journal(world) in harness.last_callbacks()

    await harness.press(
        AttActionCb(lesson=lesson(world), action="all_present").pack(),
        user_id=TEACHER_TG,
    )
    assert journal(world) in harness.last_callbacks()


async def test_journal_lists_students_with_their_current_marks(
    harness: Harness,
) -> None:
    """Each student shows the temporary mark next to the name."""
    world = harness.world
    world.temporary_marks.marks[(world.classwork.lesson.id, student_id(world, 1))] = 4

    await harness.press(journal(world), user_id=TEACHER_TG)

    assert harness.last_labels() == ["Alice", "Bob · 4", "Carol", "bot-btn-back"]
    assert "bot-journal-title" in harness.last_text()


async def test_student_shows_the_scale_remove_and_back(harness: Harness) -> None:
    """A student with a mark gets 2..5, Remove and Back."""
    world = harness.world
    world.temporary_marks.marks[(world.classwork.lesson.id, student_id(world, 0))] = 3

    await harness.press(student(world, 0), user_id=TEACHER_TG)

    assert harness.last_labels() == [
        "2",
        "3",
        "4",
        "5",
        "bot-btn-journal-remove",
        "bot-btn-back",
    ]
    assert "bot-journal-student[mark=3,name=Alice]" in harness.last_text()


async def test_student_without_a_mark_has_no_remove(harness: Harness) -> None:
    """Remove appears only when there is something to remove."""
    await harness.press(student(harness.world, 2), user_id=TEACHER_TG)

    assert "bot-btn-journal-remove" not in harness.last_labels()
    assert "bot-journal-student-none[name=Carol]" in harness.last_text()


async def test_mark_is_saved_and_the_list_comes_back(harness: Harness) -> None:
    """Tapping 5 saves the mark and returns to the list with the new value."""
    world = harness.world

    await harness.press(mark(world, 1, 5), user_id=TEACHER_TG)

    assert ("set", (student_id(world, 1), 5)) in world.temporary_marks.calls
    assert "Bob · 5" in harness.last_labels()
    assert any(t.text == "bot-journal-saved" for t in harness.toasts)


async def test_remove_deletes_the_mark(harness: Harness) -> None:
    """Remove deletes the mark and the list shows the plain name."""
    world = harness.world
    world.temporary_marks.marks[(world.classwork.lesson.id, student_id(world, 1))] = 2

    await harness.press(mark(world, 1, 0), user_id=TEACHER_TG)

    assert ("delete", student_id(world, 1)) in world.temporary_marks.calls
    assert "Bob" in harness.last_labels()
    assert any(t.text == "bot-journal-removed" for t in harness.toasts)


async def test_domain_error_becomes_a_localized_alert(harness: Harness) -> None:
    """A refused mark is explained in an alert and nothing is edited."""
    world = harness.world
    world.temporary_marks.error = NotLessonTeacherError()

    await harness.press(mark(world, 0, 4), user_id=TEACHER_TG)

    alert = harness.toasts[-1]
    assert alert.show_alert is True
    assert alert.text == "academic-not-lesson-teacher"
    assert not harness.edits


async def test_back_returns_to_the_prompt(harness: Harness) -> None:
    """Back from the list shows the lesson prompt again."""
    await harness.press(journal(harness.world, "back"), user_id=TEACHER_TG)

    assert "bot-btn-submit" in harness.last_labels()
    assert "bot-btn-journal" in harness.last_labels()


async def test_journal_stays_open_after_the_attendance_day_is_over(
    harness: Harness,
) -> None:
    """Temporary marks are kept until EMIS, so the journal works on past lessons."""
    world = harness.world
    world.classwork.state["expired"] = True

    await harness.press(journal(world), user_id=TEACHER_TG)
    await harness.press(mark(world, 1, 4), user_id=TEACHER_TG)

    assert harness.last_text() != "bot-prompt-expired"
    assert ("set", (student_id(world, 1), 4)) in world.temporary_marks.calls
    assert "Bob · 4" in harness.last_labels()
