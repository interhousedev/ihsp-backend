"""WO-5, WO-7: work-off choice in the attendance prompt, quick done, student list."""

from typing import Any
from uuid import UUID, uuid4

from app.interfaces.bot.callbacks import (
    WorkOffDoneCb,
    WorkOffPageCb,
    WorkOffPickCb,
    WorkOffPromptCb,
    WorkOffUndoCb,
)
from app.shared.contracts.callbacks import AttActionCb, AttToggleCb, MenuCb
from app.shared.ids import uuid_to_b64
from tests.bot.support.fakes import STUDENT_TG, TEACHER_TG, World
from tests.bot.support.harness import Harness

READ = {"id": str(uuid4()), "text": "Read chapter 5", "is_default": True}
SOLVE = {"id": str(uuid4()), "text": "Solve the problems", "is_default": False}


def lesson_b64(world: World) -> str:
    """The b64 id of the prompt's lesson."""
    return uuid_to_b64(world.classwork.state["lesson"].id)


def att(world: World, action: str) -> str:
    """Callback data of an attendance action."""
    return AttActionCb(lesson=lesson_b64(world), action=action).pack()


def wo(world: World, action: str) -> str:
    """Callback data of a work-off prompt action."""
    return WorkOffPromptCb(lesson=lesson_b64(world), action=action).pack()


def pick(world: World, pos: int) -> str:
    """Callback data of a template button."""
    return WorkOffPickCb(lesson=lesson_b64(world), pos=pos).pack()


async def open_checklist(harness: Harness) -> None:
    """Toggle Carol absent: renders the checklist with the work-off line."""
    data = AttToggleCb(lesson=lesson_b64(harness.world), pos=2).pack()
    await harness.press(data, user_id=TEACHER_TG)


def submits(world: World) -> list[dict[str, Any]]:
    """Arguments of the submit calls."""
    return [d for name, d in world.classwork.calls if name == "submit"]


# - - - Teacher prompt: choice - - -


async def test_default_template_is_preselected(harness: Harness) -> None:
    """WO-5: the default template shows in the checklist's work-off line."""
    harness.world.classwork_queries.templates = [READ, SOLVE]

    await open_checklist(harness)

    assert "bot-prompt-work-off[task=Read chapter 5]" in harness.last_text()
    assert wo(harness.world, "menu") in harness.last_callbacks()
    assert wo(harness.world, "text") in harness.last_callbacks()


async def test_no_default_means_none_line(harness: Harness) -> None:
    """Without a default template the line says there is none."""
    harness.world.classwork_queries.templates = [{**READ, "is_default": False}]

    await open_checklist(harness)

    assert "bot-prompt-work-off[task=bot-prompt-work-off-none]" in harness.last_text()


async def test_choose_lists_templates_with_none_and_marks_the_selected(
    harness: Harness,
) -> None:
    """The menu has None plus one button per template by position."""
    harness.world.classwork_queries.templates = [READ, SOLVE]

    await harness.press(wo(harness.world, "menu"), user_id=TEACHER_TG)

    assert harness.last_labels() == [
        "⬜ bot-btn-work-off-none",
        "✅ Read chapter 5",
        "⬜ Solve the problems",
        "bot-btn-back",
    ]
    assert harness.last_callbacks()[:3] == [pick(harness.world, i) for i in (0, 1, 2)]


async def test_choose_without_templates_explains(harness: Harness) -> None:
    """No templates: a hint, but None and Back still work."""
    await harness.press(wo(harness.world, "menu"), user_id=TEACHER_TG)

    assert harness.last_text() == "bot-work-off-no-templates"
    assert pick(harness.world, 0) in harness.last_callbacks()


async def test_picking_a_template_edits_the_checklist(harness: Harness) -> None:
    """Toggle choice: the second template replaces the default."""
    harness.world.classwork_queries.templates = [READ, SOLVE]

    await harness.press(pick(harness.world, 2), user_id=TEACHER_TG)

    assert not harness.sent
    assert "bot-prompt-work-off[task=Solve the problems]" in harness.last_text()
    assert att(harness.world, "submit") in harness.last_callbacks()


async def test_picking_none_clears_the_default(harness: Harness) -> None:
    """None is an explicit choice that beats the default."""
    harness.world.classwork_queries.templates = [READ]

    await harness.press(pick(harness.world, 0), user_id=TEACHER_TG)

    assert "bot-prompt-work-off-none" in harness.last_text()


# - - - Teacher prompt: text - - -


async def test_add_text_waits_for_a_message_with_cancel(harness: Harness) -> None:
    """Add text edits the prompt into a request and opens the FSM input."""
    await harness.press(wo(harness.world, "text"), user_id=TEACHER_TG)

    assert harness.last_text() == "bot-work-off-ask-text"
    assert harness.last_callbacks() == [wo(harness.world, "cancel_text")]
    assert await harness.state_of(TEACHER_TG) == "WorkOffStates:waiting_text"


async def test_text_is_added_to_the_template(harness: Harness) -> None:
    """The typed text joins the template and the checklist comes back."""
    harness.world.classwork_queries.templates = [READ]
    await harness.press(wo(harness.world, "text"), user_id=TEACHER_TG)

    await harness.send("Page 12 too", user_id=TEACHER_TG)

    assert "task=Read chapter 5 + Page 12 too" in harness.last_text()
    assert await harness.state_of(TEACHER_TG) is None


async def test_too_long_text_is_refused_and_input_stays(harness: Harness) -> None:
    """Over 1000 characters: a hint and the state stays."""
    await harness.press(wo(harness.world, "text"), user_id=TEACHER_TG)

    await harness.send("x" * 1001, user_id=TEACHER_TG)

    assert harness.last_text() == "bot-work-off-too-long[limit=1000]"
    assert await harness.state_of(TEACHER_TG) == "WorkOffStates:waiting_text"


async def test_voice_where_text_is_expected(harness: Harness) -> None:
    """A voice message asks for text and keeps the input open."""
    await harness.press(wo(harness.world, "text"), user_id=TEACHER_TG)

    await harness.send_voice(user_id=TEACHER_TG)

    assert await harness.state_of(TEACHER_TG) == "WorkOffStates:waiting_text"


async def test_cancel_text_returns_to_the_checklist(harness: Harness) -> None:
    """Cancel leaves the input and shows the checklist again."""
    await harness.press(wo(harness.world, "text"), user_id=TEACHER_TG)

    await harness.press(wo(harness.world, "cancel_text"), user_id=TEACHER_TG)

    assert await harness.state_of(TEACHER_TG) is None
    assert att(harness.world, "submit") in harness.last_callbacks()


# - - - Teacher prompt: save modes - - -


async def test_save_gives_absent_students_the_common_work_off(
    harness: Harness,
) -> None:
    """Save with a chosen template and text sends mode common."""
    harness.world.classwork_queries.templates = [READ]
    await open_checklist(harness)
    await harness.press(wo(harness.world, "text"), user_id=TEACHER_TG)
    await harness.send("Page 12", user_id=TEACHER_TG)

    await harness.press(att(harness.world, "submit"), user_id=TEACHER_TG)

    (call,) = submits(harness.world)
    assert call["work_off_mode"] == "common"
    assert call["common_work_off"] == {
        "template_id": READ["id"],
        "text": "Page 12",
        "due_date": None,
    }


async def test_save_without_work_off_sends_mode_none(harness: Harness) -> None:
    """Save without work-off attaches nothing even with a default."""
    harness.world.classwork_queries.templates = [READ]
    await open_checklist(harness)

    await harness.press(att(harness.world, "submit_none"), user_id=TEACHER_TG)

    (call,) = submits(harness.world)
    assert call["work_off_mode"] == "none"
    assert call["common_work_off"] is None
    assert call["from_draft"] is True


async def test_save_with_nothing_chosen_sends_mode_none(harness: Harness) -> None:
    """No template and no text: Save is the same as without work-off."""
    await open_checklist(harness)

    await harness.press(att(harness.world, "submit"), user_id=TEACHER_TG)

    assert submits(harness.world)[0]["work_off_mode"] == "none"


async def test_save_with_nobody_absent_sends_mode_none(harness: Harness) -> None:
    """A chosen work-off is not sent when no student is absent."""
    harness.world.classwork_queries.templates = [READ]

    await harness.press(att(harness.world, "submit"), user_id=TEACHER_TG)

    assert submits(harness.world)[0]["work_off_mode"] == "none"


async def test_all_present_sends_mode_none(harness: Harness) -> None:
    """Everyone present never carries a work-off."""
    harness.world.classwork_queries.templates = [READ]
    await open_checklist(harness)

    await harness.press(att(harness.world, "all_present"), user_id=TEACHER_TG)

    call = submits(harness.world)[0]
    assert call["work_off_mode"] == "none"
    assert call["from_draft"] is False


async def test_choice_is_forgotten_after_saving(harness: Harness) -> None:
    """Editing the attendance afterwards starts from the default again."""
    harness.world.classwork_queries.templates = [READ, SOLVE]
    await harness.press(pick(harness.world, 2), user_id=TEACHER_TG)
    await harness.press(att(harness.world, "submit"), user_id=TEACHER_TG)

    await harness.press(att(harness.world, "edit"), user_id=TEACHER_TG)

    assert "task=Read chapter 5" in harness.last_text()


# - - - Teacher quick done (WO-7) - - -


def teacher_items(count: int) -> list[dict[str, Any]]:
    """Open work-offs of the teacher."""
    return [
        {
            "id": str(uuid4()),
            "student_name": f"Student {i}",
            "group_name": "2TN2",
            "lesson_id": str(uuid4()),
            "date": "2026-10-19",
            "subject_name": "Physics",
            "text": "Read",
        }
        for i in range(count)
    ]


def done_data(item: dict[str, Any], page: int = 0) -> str:
    """Callback data of the item's button."""
    return WorkOffDoneCb(item=uuid_to_b64(UUID(item["id"])), page=page).pack()


async def test_teacher_list_has_a_button_per_item(harness: Harness) -> None:
    """/workoffs lists 'Student — group · DD.MM subject' buttons."""
    items = harness.world.classwork_queries.teacher_items
    items.extend(teacher_items(2))

    await harness.send("/workoffs", user_id=TEACHER_TG)

    assert harness.last_labels()[0] == "Student 0 — 2TN2 · 19.10 Physics"
    assert harness.last_callbacks()[:2] == [done_data(i) for i in items]
    assert "bot-workoffs-teacher-title[count=2]" in harness.last_text()


async def test_teacher_menu_button_opens_the_list(harness: Harness) -> None:
    """The main-menu button shows the same list."""
    harness.world.classwork_queries.teacher_items.extend(teacher_items(1))

    await harness.press(MenuCb(screen="workoffs").pack(), user_id=TEACHER_TG)

    assert harness.last_labels()[0].startswith("Student 0")


async def test_teacher_empty_list(harness: Harness) -> None:
    """Nothing open: a message and Back."""
    await harness.send("/workoffs", user_id=TEACHER_TG)

    assert "bot-workoffs-teacher-empty" in harness.last_text()
    assert harness.last_labels() == ["bot-btn-back"]


async def test_tap_marks_done_and_offers_undo(harness: Harness) -> None:
    """One tap sets done, drops the item and shows Undo for it."""
    items = harness.world.classwork_queries.teacher_items
    items.extend(teacher_items(2))
    first, second = items

    await harness.press(done_data(first), user_id=TEACHER_TG)

    calls = harness.world.classwork.calls
    assert calls == [("work_off_status", (UUID(first["id"]), "done"))]
    assert harness.last_callbacks()[0] == done_data(second)
    assert "bot-btn-work-off-undo" in harness.last_labels()
    assert "bot-workoffs-marked-done[student=Student 0]" in harness.last_text()


async def test_undo_sets_assigned_again(harness: Harness) -> None:
    """Undo puts the last marked work-off back into the list."""
    items = harness.world.classwork_queries.teacher_items
    items.extend(teacher_items(1))
    first = items[0]
    await harness.press(done_data(first), user_id=TEACHER_TG)
    undo = WorkOffUndoCb(item=uuid_to_b64(UUID(first["id"])), page=0).pack()
    assert undo in harness.last_callbacks()

    await harness.press(undo, user_id=TEACHER_TG)

    assert harness.world.classwork.calls[-1] == (
        "work_off_status",
        (UUID(first["id"]), "assigned"),
    )
    assert harness.last_callbacks()[0] == done_data(first)
    assert "bot-btn-work-off-undo" not in harness.last_labels()


async def test_teacher_list_is_paged(harness: Harness) -> None:
    """More than a page: a next button, and the next page has previous."""
    harness.world.classwork_queries.teacher_items.extend(teacher_items(10))

    await harness.send("/workoffs", user_id=TEACHER_TG)
    assert WorkOffPageCb(page=1).pack() in harness.last_callbacks()
    assert len(harness.last_callbacks()) == 8 + 1 + 1

    await harness.press(WorkOffPageCb(page=1).pack(), user_id=TEACHER_TG)

    assert WorkOffPageCb(page=0).pack() in harness.last_callbacks()
    assert harness.last_labels()[0] == "Student 8 — 2TN2 · 19.10 Physics"


# - - - Student list - - -


async def test_student_sees_open_work_offs(harness: Harness) -> None:
    """/workoffs for a student: date, lesson, subject, teacher, text, due date."""
    harness.world.classwork_queries.my_items.append(
        {
            "id": str(uuid4()),
            "lesson_id": str(uuid4()),
            "date": "2026-10-19",
            "period": 3,
            "subject_name": "Physics",
            "teacher_name": "Ivanova M.",
            "text": "Read chapter 5",
            "status": "assigned",
            "due_date": "2026-10-26",
        }
    )

    await harness.send("/workoffs", user_id=STUDENT_TG)

    text = harness.last_text()
    assert "bot-workoffs-student-item[date=19.10,period=3,subject=Physics]" in text
    assert "bot-workoffs-student-teacher[teacher=Ivanova M.]" in text
    assert "Read chapter 5" in text
    assert "bot-workoffs-student-due[due=26.10]" in text


async def test_student_menu_button_and_empty_list(harness: Harness) -> None:
    """The menu button opens the list; with no items it says so."""
    await harness.press(MenuCb(screen="workoffs").pack(), user_id=STUDENT_TG)

    assert "bot-workoffs-student-empty" in harness.last_text()
    assert harness.last_labels() == ["bot-btn-back"]
