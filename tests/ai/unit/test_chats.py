"""AI-1, AI-12: saved chats can be listed, renamed and deleted."""

from datetime import timedelta

from app.modules.ai.domain.assistant import Assistant
from app.modules.ai.domain.errors import ChatNotFoundError, WrongAssistantError
from tests.ai.conftest import AiHarness
from tests.fakes.ai.llm import text_reply

import pytest


async def test_new_chat_has_a_default_title_and_the_configured_model(
    h: AiHarness,
) -> None:
    """AI-1, AI-13: the chat starts untitled with the assistant's model."""
    chat = await h.new_chat()

    assert chat.title == "New chat"
    stored = h.store.chats[chat.id]
    assert stored.model == "anthropic/claude-haiku-4.5"


async def test_title_comes_from_the_first_message_only(h: AiHarness) -> None:
    """UF-WEB-19: the first 60 characters of the first message, once."""
    chat = await h.new_chat()
    long_text = "Explain   photosynthesis " + "very " * 30

    first = await h.say(chat.id, long_text)
    second = await h.say(chat.id, "Thanks")

    assert first.chat.title == " ".join(long_text.split())[:60]
    assert second.chat.title == first.chat.title


async def test_chat_can_be_renamed_and_deleted(h: AiHarness) -> None:
    """AI-1: rename keeps the chat; delete hides it from everyone."""
    chat = await h.new_chat()

    renamed = await h.services.rename_chat.execute(
        actor=h.student, chat_id=chat.id, title="  Biology   help "
    )
    await h.services.delete_chat.execute(actor=h.student, chat_id=chat.id)

    assert renamed.title == "Biology help"
    with pytest.raises(ChatNotFoundError):
        await h.services.get_chat.execute(actor=h.student, chat_id=chat.id)
    with pytest.raises(ChatNotFoundError):
        await h.services.rename_chat.execute(
            actor=h.student, chat_id=chat.id, title="x"
        )
    page = await h.services.list_chats.execute(
        actor=h.student, assistant=Assistant.STUDENT, cursor=None, limit=20
    )
    assert page.items == []


async def test_other_people_cannot_rename_or_delete(h: AiHarness) -> None:
    """AI-1: a stranger gets not-found."""
    chat = await h.new_chat()

    with pytest.raises(ChatNotFoundError):
        await h.services.delete_chat.execute(actor=h.other_student, chat_id=chat.id)
    with pytest.raises(ChatNotFoundError):
        await h.services.rename_chat.execute(
            actor=h.other_student, chat_id=chat.id, title="mine"
        )


async def test_chat_list_is_newest_first_with_a_cursor(h: AiHarness) -> None:
    """AI-1: cursor pagination ordered by the last message."""
    ids = []
    for index in range(3):
        chat = await h.new_chat()
        ids.append(chat.id)
        h.clock.advance(minutes=1)
        h.llm.push(text_reply("ok"))
        await h.say(chat.id, f"message {index}")
        h.clock.advance(minutes=1)

    first = await h.services.list_chats.execute(
        actor=h.student, assistant=Assistant.STUDENT, cursor=None, limit=2
    )
    second = await h.services.list_chats.execute(
        actor=h.student, assistant=Assistant.STUDENT, cursor=first.next_cursor, limit=2
    )

    assert [c.id for c in first.items] == [ids[2], ids[1]]
    assert first.next_cursor is not None
    assert [c.id for c in second.items] == [ids[0]]
    assert second.next_cursor is None


async def test_chat_lists_are_separate_per_assistant_and_role(h: AiHarness) -> None:
    """AI-1: the admin assistant has its own chats; roles pick the assistant."""
    student_chat = await h.new_chat()
    admin_chat = await h.new_chat(assistant=Assistant.ADMIN)

    admin_page = await h.services.list_chats.execute(
        actor=h.admin, assistant=Assistant.ADMIN, cursor=None, limit=20
    )

    assert [c.id for c in admin_page.items] == [admin_chat.id]
    assert student_chat.id != admin_chat.id
    with pytest.raises(WrongAssistantError):
        await h.new_chat(actor=h.student, assistant=Assistant.ADMIN)
    with pytest.raises(WrongAssistantError):
        await h.new_chat(actor=h.admin, assistant=Assistant.STUDENT)
    with pytest.raises(WrongAssistantError):
        await h.services.list_chats.execute(
            actor=h.student, assistant=Assistant.ADMIN, cursor=None, limit=20
        )


async def test_old_administration_chats_are_deleted_after_90_days(h: AiHarness) -> None:
    """AI-12: Administration chats are hard-deleted; student chats are kept."""
    admin_chat = await h.new_chat(assistant=Assistant.ADMIN)
    student_chat = await h.new_chat()
    h.clock.advance(days=91)

    removed = await h.services.purge_admin_chats.execute()

    assert removed == 1
    assert admin_chat.id not in h.store.chats and student_chat.id in h.store.chats
    assert (
        h.clock.now() - timedelta(days=90)
        > h.store.chats[student_chat.id].last_message_at
    )
