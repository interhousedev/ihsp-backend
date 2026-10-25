"""Suggest or report: the /feedback flow of linked users (kind, area, text, files)."""

from types import SimpleNamespace
from typing import Any

from app.interfaces.bot.routers.common.feedback.callbacks import (
    FeedbackAreaCb,
    FeedbackKindCb,
    FeedbackStepCb,
)
from app.interfaces.bot.routers.common.feedback.states import FeedbackStates
from app.shared.contracts.callbacks import MenuCb
from app.shared.contracts.files import FilePurpose
from tests.bot.support.fake_feedback import FakeFeedback
from tests.bot.support.fakes import STUDENT_TG
from tests.bot.support.harness import Harness

import pytest

MB = 1024 * 1024


@pytest.fixture
def feedback(harness: Harness) -> FakeFeedback:
    """The feedback module's fake, installed in the container."""
    fake = FakeFeedback()
    harness.world.container.feedback = fake
    return fake


def assistant_calls(harness: Harness) -> list[Any]:
    """Install a recording AI module and return its calls (none expected here)."""
    calls: list[Any] = []

    async def stream(**kwargs: Any) -> Any:
        calls.append(kwargs)
        if False:  # pragma: no cover - makes this an async generator
            yield None

    harness.world.container.ai = SimpleNamespace(
        send_message=SimpleNamespace(stream=stream)
    )
    return calls


async def start_flow(harness: Harness, kind: str = "bug", area: str = "lms") -> None:
    """Open the flow, pick the kind and the area, send the title and description."""
    await harness.send("/feedback")
    await harness.press(FeedbackKindCb(kind=kind).pack())
    await harness.press(FeedbackAreaCb(area=area).pack())
    await harness.send("Login fails")
    await harness.send("It loops after the second try.")


async def test_full_flow_submits_the_report(
    harness: Harness, feedback: FakeFeedback
) -> None:
    """Kind, area, title, description, no files, then Send submits and confirms."""
    await start_flow(harness)
    assert await harness.state_of(STUDENT_TG) == FeedbackStates.attachments.state

    await harness.press(FeedbackStepCb(action="skip").pack())
    assert await harness.state_of(STUDENT_TG) == FeedbackStates.confirm.state
    assert "bot-feedback-summary" in harness.last_text()

    await harness.press(FeedbackStepCb(action="send").pack())

    (report,) = feedback.submitted
    assert report["kind"] == "bug"
    assert report["area"] == "lms"
    assert report["title"] == "Login fails"
    assert report["description"] == "It loops after the second try."
    assert report["files"] == []
    assert report["source"] == "bot"
    assert "bot-feedback-sent" in harness.last_text()
    assert await harness.state_of(STUDENT_TG) is None


async def test_the_menu_button_starts_the_flow(harness: Harness) -> None:
    """The linked main menu has Suggest / report, and it asks for the kind."""
    await harness.press(MenuCb(screen="feedback").pack())

    assert await harness.state_of(STUDENT_TG) == FeedbackStates.kind.state
    assert "bot-feedback-ask-kind" in harness.last_text()


async def test_attachments_are_stored_and_sent_with_the_report(
    harness: Harness, feedback: FakeFeedback
) -> None:
    """Documents go through the files module (FEEDBACK purpose) and join the report."""
    harness.session.download_data = b"screenshot bytes"
    await start_flow(harness)

    await harness.send_document(
        user_id=STUDENT_TG, file_name="error.log", file_size=2000
    )
    await harness.press(FeedbackStepCb(action="done").pack())
    await harness.press(FeedbackStepCb(action="send").pack())

    (report,) = feedback.submitted
    assert len(report["files"]) == 1
    (stored,) = harness.world.files.stored
    assert stored["data"] == b"screenshot bytes"
    assert stored["ref"].purpose == FilePurpose.FEEDBACK
    assert stored["ref"].name == "error.log"


async def test_at_most_ten_attachments(harness: Harness) -> None:
    """The eleventh file is refused and nothing is stored for it."""
    harness.session.download_data = b"x"
    await start_flow(harness)

    for _ in range(10):
        await harness.send_document(user_id=STUDENT_TG, file_size=10)
    await harness.send_document(user_id=STUDENT_TG, file_size=10)

    assert len(harness.world.files.stored) == 10
    assert "bot-feedback-too-many-files" in harness.last_text()


async def test_a_file_over_20_mb_is_refused(harness: Harness) -> None:
    """Bots cannot take files over 20 MB: nothing is downloaded or stored."""
    await start_flow(harness)

    await harness.send_document(user_id=STUDENT_TG, file_size=21 * MB)

    assert harness.world.files.stored == []
    assert "bot-resource-too-large" in harness.last_text()
    assert await harness.state_of(STUDENT_TG) == FeedbackStates.attachments.state


async def test_rate_limit_is_said_plainly(
    harness: Harness, feedback: FakeFeedback
) -> None:
    """After 10 reports a day the user gets the limit message and no submit."""
    feedback.rate_limited = True
    await start_flow(harness)
    await harness.press(FeedbackStepCb(action="skip").pack())

    await harness.press(FeedbackStepCb(action="send").pack())

    assert feedback.submitted == []
    assert "bot-feedback-rate-limited" in harness.last_text()
    assert await harness.state_of(STUDENT_TG) is None


async def test_cancel_exits_the_flow(harness: Harness, feedback: FakeFeedback) -> None:
    """/cancel in the middle of the flow clears it and submits nothing."""
    await start_flow(harness)

    await harness.send("/cancel")

    assert await harness.state_of(STUDENT_TG) is None
    assert "bot-cancelled" in harness.last_text()
    assert feedback.submitted == []


async def test_the_assistant_is_not_called_during_the_flow(
    harness: Harness, feedback: FakeFeedback
) -> None:
    """Text typed in every feedback step stays in the flow, never with the AI."""
    calls = assistant_calls(harness)
    await harness.send("/feedback")
    await harness.send("typed while choosing a kind")
    await harness.press(FeedbackKindCb(kind="idea").pack())
    await harness.press(FeedbackAreaCb(area="ai").pack())
    await harness.send("A title")
    await harness.send("A description")
    await harness.send("text while attaching")

    assert calls == []
    assert await harness.state_of(STUDENT_TG) == FeedbackStates.attachments.state


def test_callback_data_fits_telegram_limit() -> None:
    """Every feedback button packs to at most 64 bytes."""
    packed = [
        FeedbackKindCb(kind="other").pack(),
        FeedbackAreaCb(area="notebooks").pack(),
        FeedbackStepCb(action="send").pack(),
    ]

    for data in packed:
        assert len(data.encode()) <= 64
