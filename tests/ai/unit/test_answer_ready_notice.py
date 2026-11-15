"""A web chat the user left before the answer ended tells them when it is ready."""

import asyncio
from uuid import UUID

from tests.ai.conftest import AiHarness
from tests.fakes.ai.llm import provider_error, text_reply


class FakeAnswerNotifier:
    """Records the notices instead of queueing notifications."""

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def notify_chat_answer_ready(
        self, *, user_id: UUID, chat_id: UUID, seq: int, prompt: str
    ) -> None:
        self.calls.append(
            {"user_id": user_id, "chat_id": chat_id, "seq": seq, "prompt": prompt}
        )


async def _settle(notifier: FakeAnswerNotifier) -> None:
    """Give the background turn and its hook time to end."""
    for _ in range(100):
        if notifier.calls:
            return
        await asyncio.sleep(0.01)


async def test_leaving_before_the_answer_sends_one_notice(h: AiHarness) -> None:
    """The stream is dropped after the first event; the answer still lands."""
    notifier = FakeAnswerNotifier()
    h.services.bindings.answer_notifier = notifier
    chat = await h.new_chat()
    h.llm.push(text_reply("the answer"))

    events = h.services.send_message.stream(
        actor=h.student, chat_id=chat.id, text="Why is the sky blue?", file_ids=[]
    )
    await anext(events)  # the client got the first event ...
    await events.aclose()  # ... and left
    await _settle(notifier)
    await asyncio.sleep(0.05)

    assert notifier.calls == [
        {
            "user_id": h.student.user_id,
            "chat_id": chat.id,
            "seq": 2,
            "prompt": "Why is the sky blue?",
        }
    ]


async def test_staying_until_done_sends_no_notice(h: AiHarness) -> None:
    """The client received `done`: nothing is sent."""
    notifier = FakeAnswerNotifier()
    h.services.bindings.answer_notifier = notifier
    chat = await h.new_chat()
    h.llm.push(text_reply("the answer"))

    names: list[str] = []
    stream = h.services.send_message.stream(
        actor=h.student, chat_id=chat.id, text="Hello", file_ids=[]
    )
    async for event in stream:
        names.append(event.name)
    await asyncio.sleep(0.1)

    assert names[-1] == "done"
    assert notifier.calls == []


async def test_a_failed_turn_sends_no_notice(h: AiHarness) -> None:
    """Nothing to announce when the model failed after the client left."""
    notifier = FakeAnswerNotifier()
    h.services.bindings.answer_notifier = notifier
    chat = await h.new_chat()
    h.llm.push(provider_error())

    events = h.services.send_message.stream(
        actor=h.student, chat_id=chat.id, text="Hi", file_ids=[]
    )
    try:
        await anext(events)
        await events.aclose()
    except Exception:
        pass
    await asyncio.sleep(0.1)

    assert notifier.calls == []
