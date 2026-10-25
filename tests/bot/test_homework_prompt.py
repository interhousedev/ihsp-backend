"""BOT-17, BOT-18, UF-BOT-08 steps 4-7: homework and topic from the prompt."""

from app.shared.contracts.callbacks import HomeworkPromptCb
from app.shared.ids import uuid_to_b64
from tests.bot.support.fakes import TEACHER_TG, World
from tests.bot.support.harness import Harness


def prompt_cb(world: World, action: str) -> str:
    """Callback data of a homework prompt button."""
    lesson = world.classwork.state["lesson"].id
    return HomeworkPromptCb(lesson=uuid_to_b64(lesson), action=action).pack()


async def test_add_homework_asks_for_text_in_a_new_message(harness: Harness) -> None:
    """BOT-18: after Add homework the teacher sends a text message."""
    await harness.press(prompt_cb(harness.world, "add"), user_id=TEACHER_TG)

    assert harness.sent[-1].text == "bot-homework-ask"
    assert harness.last_callbacks() == ["x"]  # Cancel
    assert await harness.state_of(TEACHER_TG) == "HomeworkStates:waiting_text"


async def test_a_voice_message_is_refused_and_the_step_stays_open(
    harness: Harness,
) -> None:
    """UF-BOT-08 alternative 5a: "Please send homework as text"."""
    await harness.press(prompt_cb(harness.world, "add"), user_id=TEACHER_TG)

    await harness.send_voice(user_id=TEACHER_TG)

    assert harness.last_text() == "bot-homework-text-only"
    assert await harness.state_of(TEACHER_TG) == "HomeworkStates:waiting_text"
    assert not [c for c in harness.world.classwork.calls if c[0] == "set_homework"]


async def test_text_is_previewed_and_saved_with_save(harness: Harness) -> None:
    """BOT-18: preview with Save / Edit / Cancel, then set_homework."""
    await harness.press(prompt_cb(harness.world, "add"), user_id=TEACHER_TG)

    await harness.send("Exercises 1-5 on page 40", user_id=TEACHER_TG)

    assert "bot-homework-preview[text=Exercises 1-5 on page 40]" == harness.last_text()
    assert harness.last_labels() == ["bot-btn-save", "bot-btn-edit", "bot-btn-cancel"]

    await harness.press(prompt_cb(harness.world, "save"), user_id=TEACHER_TG)

    assert ("set_homework", "Exercises 1-5 on page 40") in harness.world.classwork.calls
    assert harness.last_text().startswith("bot-homework-saved")
    assert await harness.state_of(TEACHER_TG) is None


async def test_edit_asks_for_the_text_again(harness: Harness) -> None:
    """UF-BOT-08 alternative 6a: Edit, then the teacher sends the text again."""
    await harness.press(prompt_cb(harness.world, "add"), user_id=TEACHER_TG)
    await harness.send("first", user_id=TEACHER_TG)

    await harness.press(prompt_cb(harness.world, "edit"), user_id=TEACHER_TG)
    await harness.send("second", user_id=TEACHER_TG)
    await harness.press(prompt_cb(harness.world, "save"), user_id=TEACHER_TG)

    assert ("set_homework", "second") in harness.world.classwork.calls
    assert ("set_homework", "first") not in harness.world.classwork.calls


async def test_cancel_on_the_preview_saves_nothing(harness: Harness) -> None:
    """BOT-4: Cancel drops the draft text."""
    await harness.press(prompt_cb(harness.world, "add"), user_id=TEACHER_TG)
    await harness.send("draft", user_id=TEACHER_TG)

    await harness.press(prompt_cb(harness.world, "cancel"), user_id=TEACHER_TG)

    assert harness.last_text() == "bot-homework-cancelled"
    assert not [c for c in harness.world.classwork.calls if c[0] == "set_homework"]
    assert await harness.state_of(TEACHER_TG) is None


async def test_too_long_text_is_not_previewed(harness: Harness) -> None:
    """The preview must fit in a message."""
    await harness.press(prompt_cb(harness.world, "add"), user_id=TEACHER_TG)

    await harness.send("x" * 2001, user_id=TEACHER_TG)

    assert harness.last_text() == "bot-homework-too-long[limit=2000]"
    assert await harness.state_of(TEACHER_TG) == "HomeworkStates:waiting_text"


async def test_no_homework_closes_the_prompt(harness: Harness) -> None:
    """UF-BOT-08 alternative 4b: No homework closes the prompt without buttons."""
    harness.world.classwork.state["attendance_submitted"] = True

    await harness.press(prompt_cb(harness.world, "none"), user_id=TEACHER_TG)

    assert "bot-prompt-no-homework" in harness.last_text()
    assert harness.last().reply_markup is None
    assert not [c for c in harness.world.classwork.calls if c[0] == "clear_homework"]


async def test_no_homework_clears_homework_that_was_set(harness: Harness) -> None:
    """If homework exists (set on the web), No homework removes it."""
    harness.world.classwork.state["attendance_submitted"] = True
    harness.world.classwork.state["homework_text"] = "old"

    await harness.press(prompt_cb(harness.world, "none"), user_id=TEACHER_TG)

    assert [c[0] for c in harness.world.classwork.calls].count("clear_homework") == 1
    assert "bot-prompt-no-homework" in harness.last_text()


async def test_topic_is_saved_straight_away(harness: Harness) -> None:
    """BOT-17, ACA-21: Set topic, then a text message sets the topic."""
    await harness.press(prompt_cb(harness.world, "topic"), user_id=TEACHER_TG)
    assert harness.sent[-1].text == "bot-topic-ask"

    await harness.send("Derivatives", user_id=TEACHER_TG)

    assert ("set_topic", "Derivatives") in harness.world.classwork.calls
    assert harness.last_text() == "bot-topic-saved[topic=Derivatives]"
    assert await harness.state_of(TEACHER_TG) is None


async def test_a_command_ends_the_homework_input(harness: Harness) -> None:
    """A slash command is not homework text."""
    await harness.press(prompt_cb(harness.world, "add"), user_id=TEACHER_TG)

    await harness.send("/menu", user_id=TEACHER_TG)

    assert await harness.state_of(TEACHER_TG) is None
    assert not [c for c in harness.world.classwork.calls if c[0] == "set_homework"]
