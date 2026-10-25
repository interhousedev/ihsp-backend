"""The error middleware: user message with an error id, admin report (21ID style)."""

from app.shared.base_error import BaseError, NotFoundError
from tests.bot.support.fakes import ADMIN_CHAT, STUDENT_TG
from tests.bot.support.harness import Harness

from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import AnswerCallbackQuery, EditMessageText


class QuietError(BaseError):
    """An expected error whose user must not be bothered."""

    code = "test/quiet"
    status = 400
    message_key = "error-validation"


class BrokenError(BaseError):
    """An expected failure with a server status."""

    code = "test/broken"
    status = 503
    message_key = "error-internal"


def error_id_of(text: str) -> str:
    """Extract the id from ``bot-error-id[error_id=<uuid>]``."""
    return text.rsplit("error_id=", 1)[1].rstrip("]")


def texts_to(harness: Harness, chat_id: int) -> list[str]:
    """Texts the bot sent to one chat."""
    return [m.text or "" for m in harness.sent if m.chat_id == chat_id]


async def test_unexpected_error_tells_the_user_and_reports_to_the_admin(
    harness: Harness,
) -> None:
    """The user gets a friendly text and the error id; the admin gets the trace."""
    harness.world.schedule.error = ValueError("database is on fire")

    await harness.send("/today")

    to_user = texts_to(harness, STUDENT_TG)
    report = "".join(texts_to(harness, ADMIN_CHAT))
    assert to_user[0].startswith("bot-error-generic\n\nbot-error-id[error_id=")
    assert "ValueError: database is on fire" in report
    assert error_id_of(to_user[0]) in report


async def test_expected_errors_are_shown_without_bothering_the_admin(
    harness: Harness,
) -> None:
    """A 4xx domain error is translated by its message key; no admin report."""
    harness.world.schedule.error = NotFoundError()

    await harness.send("/today")

    assert [m.chat_id for m in harness.sent] == [STUDENT_TG]
    assert texts_to(harness, STUDENT_TG)[0].startswith(
        "error-not-found\n\nbot-error-id"
    )


async def test_server_side_domain_errors_are_reported_to_the_admin(
    harness: Harness,
) -> None:
    """A BaseError with status 500+ is a problem for the team."""
    harness.world.schedule.error = BrokenError()

    await harness.send("/today")

    assert ADMIN_CHAT in [m.chat_id for m in harness.sent]


async def test_notify_user_false_keeps_the_user_out_of_it(harness: Harness) -> None:
    """BaseError(notify_user=False) sends nothing to the user."""
    harness.world.schedule.error = QuietError(notify_user=False)

    await harness.send("/today")

    assert harness.sent == []


async def test_a_failing_button_is_answered_with_an_alert(harness: Harness) -> None:
    """For a button press the error is shown as a callback alert."""
    harness.world.schedule.error = ValueError("database is on fire")

    await harness.press("m:today")

    alert = harness.session.calls(AnswerCallbackQuery)[-1]
    assert alert.show_alert is True
    assert alert.text is not None
    assert alert.text.startswith("bot-error-generic")
    assert len(alert.text) <= 200


async def test_a_stale_callback_query_is_ignored(harness: Harness) -> None:
    """21ID: "query is too old" is not an error worth reporting."""
    harness.session.queue(
        AnswerCallbackQuery,
        TelegramBadRequest(
            method=AnswerCallbackQuery(callback_query_id="x"),
            message="Bad Request: query is too old and response timeout expired",
        ),
    )

    await harness.press("none")

    assert harness.sent == []


async def test_editing_to_identical_content_is_not_an_error(harness: Harness) -> None:
    """Telegram refuses a no-op edit; the bot treats it as done."""
    harness.session.queue(
        EditMessageText,
        TelegramBadRequest(
            method=EditMessageText(text="x"),
            message="Bad Request: message is not modified: same content as before",
        ),
    )

    await harness.press("m:menu")

    assert harness.sent == []
    assert harness.toasts
