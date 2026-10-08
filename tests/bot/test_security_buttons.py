"""Cancel the OTP reset and "This was not me" (FINAL_PLAN B14 step 8)."""

from app.shared.contracts.callbacks import NotMeCb, OtpCancelCb
from app.shared.ids import new_id, uuid_to_b64
from tests.bot.support.harness import Harness

UNLINKED = 7777


async def test_otp_cancel_calls_the_identity_use_case(harness: Harness) -> None:
    """The button calls cancel_otp_reset with the request id and confirms."""
    request_id = new_id()

    await harness.press(OtpCancelCb(request=uuid_to_b64(request_id)).pack())

    assert harness.world.cancel_otp.requests == [request_id]
    assert harness.last_text() == "bot-otp-cancelled"


async def test_otp_cancel_works_even_if_the_account_was_unlinked(
    harness: Harness,
) -> None:
    """The request id is the proof, so the button needs no linked account."""
    request_id = new_id()

    await harness.press(
        OtpCancelCb(request=uuid_to_b64(request_id)).pack(), user_id=UNLINKED
    )

    assert harness.world.cancel_otp.requests == [request_id]


async def test_not_me_points_to_the_security_settings(harness: Harness) -> None:
    """UF-BOT-02: Not me opens the ID service's security settings."""
    await harness.press(NotMeCb(kind="otp").pack())

    assert harness.sent[-1].text == "bot-not-me-otp"
    link = harness.last_buttons()[0][0]
    assert link.url == "http://localhost:3001/security/"


async def test_not_me_for_telegram_links_uses_its_own_text(harness: Harness) -> None:
    """The text depends on what was not the user's doing."""
    await harness.press(NotMeCb(kind="tg").pack())

    assert harness.sent[-1].text == "bot-not-me-tg"
