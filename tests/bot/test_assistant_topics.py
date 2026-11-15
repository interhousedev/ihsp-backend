"""Private-chat topics: one topic per AI chat, UI blocks at the end of the answer."""

from tests.bot.support.fake_ai import FakeAi, call_view, delta, done
from tests.bot.support.harness import Harness

import pytest
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import (
    CreateForumTopic,
    DeleteForumTopic,
    EditForumTopic,
    GetForumTopicIconStickers,
    SendMessage,
)
from aiogram.types import Sticker

BLOCK = 'root = Stack([chart])\nchart = BarChart(["Mon", "Tue"], [3, 5], "Marks")\n'


@pytest.fixture
def ai(harness: Harness) -> FakeAi:
    """The scripted assistant, installed in the container."""
    fake = FakeAi()
    harness.world.container.ai = fake
    return fake


def _sticker(emoji: str, emoji_id: str) -> Sticker:
    return Sticker(
        file_id=emoji_id,
        file_unique_id=emoji_id,
        type="custom_emoji",
        width=1,
        height=1,
        is_animated=False,
        is_video=False,
        emoji=emoji,
        custom_emoji_id=emoji_id,
    )


@pytest.fixture(autouse=True)
def _fresh_icons(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.interfaces.bot.assistant.topics as topics

    monkeypatch.setattr(topics, "_stickers", None)


async def test_ui_block_closes_the_answer_message(harness: Harness, ai: FakeAi) -> None:
    call = call_view(status="done", tool="show_ui_block", ui_block=BLOCK)
    ai.play([delta("Here are your marks."), done("Here are your marks.", calls=[call])])

    await harness.send("show marks")

    texts = [m.text or "" for m in harness.session.calls(SendMessage)]
    assert len(texts) == 1
    assert texts[0].index("Here are your marks.") < texts[0].index("Mon")


async def test_one_topic_per_chat_with_a_persisted_mapping(
    harness: Harness, ai: FakeAi
) -> None:
    harness.enable_topics()
    harness.session.queue(
        GetForumTopicIconStickers, [_sticker("🔥", "icon-fire"), _sticker("💻", "i2")]
    )

    await harness.send("Solve this math problem")
    await harness.send("and one more", thread_id=500 + 1)

    created = harness.session.calls(CreateForumTopic)
    assert len(created) == 1
    assert created[0].name == "Solve this math problem"
    assert created[0].icon_custom_emoji_id == "icon-fire"
    chat_id = ai.chats[0]
    mapped = await ai.telegram_topics.of_chat(chat_id)
    assert mapped is not None
    assert mapped.message_thread_id == 501
    assert [s["chat_id"] for s in ai.sent] == [chat_id, chat_id]
    assert all(m.message_thread_id == 501 for m in harness.sent)


async def test_a_topic_message_goes_to_the_mapped_chat(
    harness: Harness, ai: FakeAi
) -> None:
    harness.enable_topics()
    await harness.send("first")  # root: creates chat A and its topic (thread 501)
    await harness.send("/new")
    await harness.send("second")  # root again: chat B, topic 502
    assert len(ai.chats) == 2

    await harness.send("back to the first", thread_id=501)

    assert ai.sent[-1]["chat_id"] == ai.chats[0]
    assert len(ai.chats) == 2


async def test_a_topic_made_by_hand_becomes_a_chat(
    harness: Harness, ai: FakeAi
) -> None:
    harness.enable_topics()

    await harness.send("hello", thread_id=77)

    assert not harness.session.calls(CreateForumTopic)
    mapped = await ai.telegram_topics.of_thread(1001, 77)
    assert mapped is not None
    assert ai.sent[0]["chat_id"] == mapped.chat_id


async def test_without_topics_nothing_is_created(harness: Harness, ai: FakeAi) -> None:
    await harness.send("hello")
    assert not harness.session.calls(CreateForumTopic)
    assert harness.sent[-1].message_thread_id is None


async def test_telegram_refusing_the_topic_falls_back(
    harness: Harness, ai: FakeAi
) -> None:
    harness.enable_topics()
    harness.session.queue(
        CreateForumTopic,
        TelegramBadRequest(method=CreateForumTopic(chat_id=1, name="x"), message="no"),
    )
    await harness.send("hello")
    assert ai.sent
    assert harness.sent[-1].message_thread_id is None


async def test_a_renamed_chat_renames_the_topic(harness: Harness, ai: FakeAi) -> None:
    harness.enable_topics()
    await harness.send("first message")
    ai.titles[ai.chats[0]] = "Marks of October"

    await harness.send("more", thread_id=501)

    edits = harness.session.calls(EditForumTopic)
    assert [e.name for e in edits] == ["Marks of October"]
    assert edits[0].message_thread_id == 501


async def _open_delete(harness: Harness) -> None:
    harness.enable_topics()
    await harness.send("first message")
    await harness.send("/delete", thread_id=501)


async def test_delete_confirm_removes_chat_and_topic(
    harness: Harness, ai: FakeAi
) -> None:
    await _open_delete(harness)
    assert "bot-ai-delete-confirm" in harness.last_text()
    yes, _ = harness.last_callbacks()

    await harness.press(yes, thread_id=501)

    assert ai.deleted == [ai.chats[0]]
    deleted = harness.session.calls(DeleteForumTopic)
    assert [d.message_thread_id for d in deleted] == [501]
    assert await ai.telegram_topics.of_chat(ai.chats[0]) is None


async def test_delete_cancel_keeps_both(harness: Harness, ai: FakeAi) -> None:
    await _open_delete(harness)
    _, cancel = harness.last_callbacks()

    await harness.press(cancel, thread_id=501)

    assert not ai.deleted
    assert not harness.session.calls(DeleteForumTopic)
    assert await ai.telegram_topics.of_chat(ai.chats[0]) is not None
    assert "bot-ai-delete-cancelled" in harness.last_text()


async def test_delete_outside_a_topic_only_explains(
    harness: Harness, ai: FakeAi
) -> None:
    await harness.send("/delete")
    assert "bot-ai-delete-outside" in harness.last_text()
    assert not ai.deleted
