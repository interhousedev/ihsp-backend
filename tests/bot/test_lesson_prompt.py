"""BOT-16, BOT-17, BOT-19, UF-BOT-08: the attendance step of the lesson prompt."""

from app.shared.base_error import ConflictError, ForbiddenError
from app.shared.contracts.callbacks import AttActionCb, AttToggleCb
from app.shared.ids import new_id, uuid_to_b64
from tests.bot.support.fakes import STUDENT_TG, TEACHER_TG, World
from tests.bot.support.harness import Harness


class AttendanceWindowClosedError(ForbiddenError):
    """Same code as the classwork module's error."""

    code = "attendance/window-closed"


def lesson_id(world: World):  # type: ignore[no-untyped-def]
    """The id of the prompt's lesson."""
    return world.classwork.state["lesson"].id


def toggle_data(world: World, pos: int) -> str:
    """Callback data of a roster button."""
    return AttToggleCb(lesson=uuid_to_b64(lesson_id(world)), pos=pos).pack()


def action_data(world: World, action: str) -> str:
    """Callback data of an attendance action button."""
    return AttActionCb(lesson=uuid_to_b64(lesson_id(world)), action=action).pack()


async def test_toggle_edits_the_same_message_with_a_cross_on_the_student(
    harness: Harness,
) -> None:
    """BOT-17: tapping a student marks them absent (✗) in the same message."""
    await harness.press(toggle_data(harness.world, 1), user_id=TEACHER_TG)

    assert not harness.sent
    assert "✗ Bob" in harness.last_labels()
    assert "Alice" in harness.last_labels()
    assert ("toggle", 1) in harness.world.classwork.calls


async def test_toggling_twice_removes_the_cross(harness: Harness) -> None:
    """A second tap makes the student present again."""
    await harness.press(toggle_data(harness.world, 1), user_id=TEACHER_TG)
    await harness.press(toggle_data(harness.world, 1), user_id=TEACHER_TG)

    assert "Bob" in harness.last_labels()
    assert "✗ Bob" not in harness.last_labels()


async def test_checklist_header_says_when_the_lesson_ends(harness: Harness) -> None:
    """UF-BOT-08 step 1: "2TN2 · Physics ends in 5 minutes"."""
    await harness.press(toggle_data(harness.world, 0), user_id=TEACHER_TG)

    header = harness.last_text().splitlines()[0]
    assert header == "<b>bot-prompt-ends-in[minutes=5,title=2TN2 · Physics]</b>"


async def test_submit_saves_the_draft_with_the_version_it_started_from(
    harness: Harness,
) -> None:
    """BOT-17: Submit calls submit_attendance(from_draft=True, base_version=...)."""
    await harness.press(toggle_data(harness.world, 2), user_id=TEACHER_TG)

    await harness.press(action_data(harness.world, "submit"), user_id=TEACHER_TG)

    submit = [data for name, data in harness.world.classwork.calls if name == "submit"]
    assert submit == [
        {"absent": None, "from_draft": True, "base_version": 3, "source": "bot"}
    ]


async def test_after_submit_the_message_shows_the_count_and_the_homework_step(
    harness: Harness,
) -> None:
    """UF-BOT-08 steps 3-4: "Attendance: N absent", then Add / No homework."""
    await harness.press(toggle_data(harness.world, 2), user_id=TEACHER_TG)

    await harness.press(action_data(harness.world, "submit"), user_id=TEACHER_TG)

    assert "bot-prompt-absent[count=1]" in harness.last_text()
    assert harness.last_labels() == [
        "bot-btn-edit-attendance",
        "bot-btn-add-homework",
        "bot-btn-no-homework",
        "bot-btn-topic",
    ]


async def test_everyone_present_submits_an_empty_absent_list(harness: Harness) -> None:
    """BOT-17: Everyone present finishes the step without a draft."""
    await harness.press(action_data(harness.world, "all_present"), user_id=TEACHER_TG)

    submit = [data for name, data in harness.world.classwork.calls if name == "submit"]
    assert submit[0]["absent"] == []
    assert submit[0]["from_draft"] is False
    assert "bot-prompt-all-present" in harness.last_text()


async def test_edit_attendance_shows_the_checklist_again(harness: Harness) -> None:
    """UF-BOT-08: Edit attendance reopens the roster after a submit."""
    await harness.press(action_data(harness.world, "all_present"), user_id=TEACHER_TG)

    await harness.press(action_data(harness.world, "edit"), user_id=TEACHER_TG)

    assert "Alice" in harness.last_labels()
    assert "bot-btn-submit" in harness.last_labels()


async def test_conflict_shows_the_current_list_with_a_note(harness: Harness) -> None:
    """UF-BOT-08 alternative 3a: someone else changed the attendance."""
    harness.world.classwork.submit_error = ConflictError()

    await harness.press(action_data(harness.world, "submit"), user_id=TEACHER_TG)

    assert "bot-prompt-conflict" in harness.last_text()
    assert "Alice" in harness.last_labels()
    assert "bot-btn-submit" in harness.last_labels()


async def test_an_expired_prompt_points_to_the_staff_portal(harness: Harness) -> None:
    """BOT-19: the next day the buttons say to use the staff portal."""
    harness.world.classwork.state["expired"] = True

    await harness.press(toggle_data(harness.world, 0), user_id=TEACHER_TG)

    assert harness.last_text() == "bot-prompt-expired"
    link = harness.last_buttons()[0][0]
    assert link.web_app is not None
    assert link.web_app.url.startswith("http://localhost:3003/lessons/view/?id=")


async def test_window_closed_error_is_shown_as_expired(harness: Harness) -> None:
    """The classwork module can refuse a late toggle with its window error."""
    harness.world.classwork.prompt_error = AttendanceWindowClosedError()

    await harness.press(action_data(harness.world, "edit"), user_id=TEACHER_TG)

    assert harness.last_text() == "bot-prompt-expired"


async def test_a_reassigned_lesson_is_reported(harness: Harness) -> None:
    """UF-BOT-08: the teacher is no longer the lesson's teacher."""
    harness.world.classwork.prompt_error = ForbiddenError()

    await harness.press(action_data(harness.world, "edit"), user_id=TEACHER_TG)

    assert harness.last_text() == "bot-prompt-reassigned"


async def test_students_cannot_press_attendance_buttons(harness: Harness) -> None:
    """The prompt belongs to teachers; a student only gets an out-of-date note."""
    await harness.press(toggle_data(harness.world, 0), user_id=STUDENT_TG)

    assert ("toggle", 0) not in harness.world.classwork.calls
    assert harness.toasts[-1].text == "bot-stale-button"


async def test_unassigned_students_are_under_their_own_heading(
    harness: Harness,
) -> None:
    """BOT-17: students without a subgroup are in a separate section."""
    roster = harness.world.classwork.state["roster"]
    roster[2]["subgroup_unset"] = True

    await harness.press(toggle_data(harness.world, 0), user_id=TEACHER_TG)

    labels = harness.last_labels()
    assert "bot-prompt-no-subgroup[group=2TN2]" in labels
    assert labels.index("Carol") > labels.index("bot-prompt-no-subgroup[group=2TN2]")


async def test_a_huge_roster_stays_within_telegrams_100_button_limit(
    harness: Harness,
) -> None:
    """Telegram allows 100 buttons; the rest goes to the staff portal."""
    harness.world.classwork.state["roster"] = [
        {
            "position": index,
            "user_id": new_id(),
            "name": f"Student {index}",
            "group_name": "2TN2",
            "subgroup_unset": False,
            "absent": False,
        }
        for index in range(150)
    ]

    await harness.press(toggle_data(harness.world, 0), user_id=TEACHER_TG)

    assert len(harness.last_labels()) <= 100
    assert "bot-prompt-roster-cut[count=70]" in harness.last_text()
    assert harness.last_buttons()[-1][0].web_app is not None


async def test_merged_lessons_group_students_under_group_headings(
    harness: Harness,
) -> None:
    """BOT-17: a lesson of several groups shows each group's students together."""
    roster = harness.world.classwork.state["roster"]
    roster[2]["group_name"] = "2TN3"

    await harness.press(toggle_data(harness.world, 0), user_id=TEACHER_TG)

    labels = harness.last_labels()
    assert "— 2TN2 —" in labels
    assert "— 2TN3 —" in labels
