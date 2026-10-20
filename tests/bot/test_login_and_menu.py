"""BOT-5..9, UF-BOT-01, UF-BOT-03: Log in button, main menu by role, commands."""

from tests.bot.support.fakes import STUDENT_TG, TEACHER_TG
from tests.bot.support.harness import Harness

from aiogram.methods import SetChatMenuButton
from aiogram.types import MenuButtonWebApp

UNLINKED = 7777


async def test_start_unlinked_shows_login_web_app_button(harness: Harness) -> None:
    """BOT-5, ID-19: /start from an unlinked account offers Log in as a mini app."""
    await harness.send("/start", user_id=UNLINKED)

    button = harness.last_buttons()[0][0]
    assert harness.last_text() == "bot-login-welcome"
    assert button.text == "bot-btn-login"
    assert button.web_app is not None
    assert button.web_app.url == "http://localhost:3001/telegram/"


async def test_start_with_a_payload_behaves_like_start(harness: Harness) -> None:
    """BOT-6: there are no deep links; /start <anything> is /start."""
    await harness.send("/start whatever-token", user_id=UNLINKED)

    assert harness.last_text() == "bot-login-welcome"


async def test_unlinked_text_and_buttons_lead_to_login(harness: Harness) -> None:
    """BOT-5: an unlinked account never reaches a screen, only Log in."""
    await harness.send("hello", user_id=UNLINKED)
    await harness.press("m:marks", user_id=UNLINKED)

    texts = [m.text for m in harness.sent] + [e.text for e in harness.edits]
    assert texts == ["bot-login-welcome", "bot-login-welcome"]


async def test_linked_student_gets_the_student_menu(harness: Harness) -> None:
    """BOT-9: students see Today, Marks, Homework, Mail, Settings and Open app."""
    await harness.send("/start")

    assert harness.last_text() == (
        "bot-menu-greeting[login=brastilov.aleksey,name=Aleksey]"
    )
    assert harness.last_callbacks() == [
        "m:today",
        "m:marks",
        "m:homework",
        "m:workoffs",
        "m:mail",
        "m:settings",
    ]
    app_button = harness.last_buttons()[-1][0]
    assert app_button.web_app is not None
    assert app_button.web_app.url == "http://localhost:3002"


async def test_teacher_menu_has_current_lesson_and_the_staff_portal(
    harness: Harness,
) -> None:
    """BOT-8, BOT-9: teachers see Today, Current lesson, Settings; Open app is staff."""
    await harness.send("/menu", user_id=TEACHER_TG)

    assert harness.last_callbacks() == [
        "m:today",
        "m:lesson",
        "m:workoffs",
        "m:settings",
    ]
    app_button = harness.last_buttons()[-1][0]
    assert app_button.web_app is not None
    assert app_button.web_app.url == "http://localhost:3003"


async def test_menu_command_sets_the_per_role_menu_button(harness: Harness) -> None:
    """BOT-8: the chat menu button opens the mini app of the user's role."""
    await harness.send("/start", user_id=TEACHER_TG)

    (call,) = harness.session.calls(SetChatMenuButton)
    assert call.chat_id == TEACHER_TG
    assert isinstance(call.menu_button, MenuButtonWebApp)
    assert call.menu_button.web_app.url == "http://localhost:3003"


async def test_unread_notifications_are_shown_in_the_menu(harness: Harness) -> None:
    """The menu mentions unread notifications of the web center."""
    harness.world.notify.unread = 3

    await harness.send("/menu")

    assert "bot-menu-unread[count=3]" in harness.last_text()


async def test_menu_button_press_edits_the_same_message(harness: Harness) -> None:
    """UF-BOT-03: screens are edited in place, not sent again."""
    await harness.press("m:menu")

    assert not harness.sent
    assert (harness.edits[-1].text or "").startswith("bot-menu-greeting")


async def test_help_shows_help_text_and_menu(harness: Harness) -> None:
    """BOT-9: /help opens the help screen with the menu buttons."""
    await harness.send("/help")

    assert harness.last_text() == "bot-help"
    assert "m:today" in harness.last_callbacks()


async def test_unknown_text_gets_a_hint_and_the_menu(harness: Harness) -> None:
    """BOT-23: an unexpected message gets a short hint and the menu."""
    await harness.send("what is this")

    assert harness.last_text().startswith("bot-hint-unexpected")
    assert "m:today" in harness.last_callbacks()


async def test_unknown_button_says_it_is_out_of_date(harness: Harness) -> None:
    """A button nothing handles is answered, not left spinning."""
    await harness.press("zz:old")

    assert harness.toasts[-1].text == "bot-stale-button"


async def test_cancel_clears_the_state_and_shows_the_menu(harness: Harness) -> None:
    """BOT-4: Cancel works in every step."""
    await harness.press("mc:new", user_id=STUDENT_TG)
    assert await harness.state_of(STUDENT_TG) is not None

    await harness.send("/cancel")

    assert await harness.state_of(STUDENT_TG) is None
    assert harness.last_text().startswith("bot-cancelled")


async def test_slash_command_leaves_a_half_finished_input(harness: Harness) -> None:
    """A command abandons the current step instead of being taken as its answer."""
    await harness.press("mc:new")

    await harness.send("/today")

    assert await harness.state_of(STUDENT_TG) is None
    assert "bot-today-title" in harness.last_text()


async def test_the_label_buttons_do_nothing(harness: Harness) -> None:
    """Heading buttons answer the callback and change nothing."""
    await harness.press("none")

    assert harness.toasts
    assert not harness.edits
