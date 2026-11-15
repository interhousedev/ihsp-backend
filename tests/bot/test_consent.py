"""Legal consent: the bot refuses a linked user who has not accepted the documents."""

from types import SimpleNamespace
from uuid import UUID

from app.modules.legal.domain.errors import LegalAcceptanceRequiredError
from app.shared.contracts.callbacks import NotMeCb, OtpCancelCb
from app.shared.ids import new_id, uuid_to_b64
from tests.bot.support.fakes import STUDENT_TG
from tests.bot.support.harness import Harness
from tests.bot.support.recording_bot import _sender, _update

from aiogram.methods import AnswerInlineQuery


class Gate:
    """A consent gate whose answer the test switches."""

    def __init__(self) -> None:
        """Start with consent pending."""
        self.pending = True

    async def execute(self, user_id: UUID) -> None:
        """Refuse while pending."""
        if self.pending:
            raise LegalAcceptanceRequiredError(params={"kinds": "privacy"})


def enable(harness: Harness) -> Gate:
    """Install the gate in the container."""
    gate = Gate()
    harness.world.container.legal = SimpleNamespace(require_consent=gate)
    return gate


async def test_a_message_gets_the_notice_and_an_accept_link(harness: Harness) -> None:
    enable(harness)

    await harness.send("/menu")

    assert harness.last_text() == "bot-legal-acceptance-required"
    assert len(harness.sent) == 1
    [[button]] = harness.last_buttons()
    assert button.text == "bot-legal-accept-button"
    assert button.url


async def test_a_button_press_is_answered_with_an_alert(harness: Harness) -> None:
    enable(harness)

    await harness.press("st:lang:uz")

    assert [t.text for t in harness.toasts] == ["bot-legal-acceptance-required"]
    assert not harness.sent


async def test_after_accepting_the_bot_works_again(harness: Harness) -> None:
    gate = enable(harness)
    await harness.send("/menu")
    gate.pending = False

    await harness.send("/menu")

    assert harness.last_text() != "bot-legal-acceptance-required"


async def test_unlinked_users_are_not_asked(harness: Harness) -> None:
    enable(harness)

    await harness.send("/start", user_id=7777)

    assert harness.last_text() != "bot-legal-acceptance-required"


async def test_security_buttons_work_without_consent(harness: Harness) -> None:
    """OTP cancel and "not me" protect the account, so the gate lets them pass."""
    enable(harness)
    request_id = new_id()

    await harness.press(OtpCancelCb(request=uuid_to_b64(request_id)).pack())
    await harness.press(NotMeCb(kind="tg").pack())

    assert harness.world.cancel_otp.requests == [request_id]
    assert harness.sent[-1].text == "bot-not-me-tg"
    assert "bot-legal-acceptance-required" not in [t.text for t in harness.toasts]


async def test_an_inline_query_gets_no_results_while_pending(
    harness: Harness,
) -> None:
    """Inline mode is gated too: an empty, personal, uncached answer."""
    enable(harness)
    query = {"id": "iq1", "from": _sender(STUDENT_TG), "query": "x", "offset": ""}

    await harness.dp.feed_update(
        harness.bot,
        _update(harness.bot, 9, inline_query=query),
        container=harness.world.container,
    )

    [answer] = harness.session.calls(AnswerInlineQuery)
    assert answer.results == []
    assert answer.is_personal is True
    assert answer.cache_time == 0
