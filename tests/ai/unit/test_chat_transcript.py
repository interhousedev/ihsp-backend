"""NB-SRC-CHAT: AiQueries.chat_transcript, the text of a chat for a notebook source."""

from uuid import uuid4

from app.modules.ai.domain.assistant import Assistant
from tests.ai.conftest import AiHarness
from tests.fakes.ai.llm import text_reply, tool_reply


async def test_transcript_has_user_and_assistant_text_in_order(h: AiHarness) -> None:
    """Messages come as {seq, role, text} with the chat title."""
    chat = await h.new_chat()
    await h.say(chat.id, "What is photosynthesis?")
    h.llm.push(text_reply("Plants turn light into energy."))
    await h.say(chat.id, "Say it shorter")

    transcript = await h.services.public.chat_transcript(
        h.student.user_id, chat.id, None
    )

    assert transcript is not None
    assert transcript["title"] == "What is photosynthesis?"
    assert [(m["seq"], m["role"], m["text"]) for m in transcript["messages"]] == [
        (1, "user", "What is photosynthesis?"),
        (2, "assistant", "ok"),
        (3, "user", "Say it shorter"),
        (4, "assistant", "Plants turn light into energy."),
    ]
    assert transcript["last_seq"] == 4


async def test_tool_calls_and_empty_assistant_texts_are_dropped(h: AiHarness) -> None:
    """The assistant message that only held a tool call has no text: skipped."""
    h.marks.summary = []
    chat = await h.new_chat()
    h.llm.push(tool_reply(("get_my_subjects", {})), text_reply("No subjects yet."))
    await h.say(chat.id, "What do I study?")

    transcript = await h.services.public.chat_transcript(
        h.student.user_id, chat.id, None
    )

    assert transcript is not None
    assert [m["text"] for m in transcript["messages"]] == [
        "What do I study?",
        "No subjects yet.",
    ]
    assert transcript["last_seq"] == 2  # the tool round is inside the answer
    assert "get_my_subjects" not in str(transcript)


async def test_until_seq_cuts_the_text_but_last_seq_is_the_whole_chat(
    h: AiHarness,
) -> None:
    """A snapshot up to message 2 knows the chat has newer messages."""
    chat = await h.new_chat()
    await h.say(chat.id, "one")
    await h.say(chat.id, "two")

    snapshot = await h.services.public.chat_transcript(h.student.user_id, chat.id, 2)

    assert snapshot is not None
    assert [m["text"] for m in snapshot["messages"]] == ["one", "ok"]
    assert snapshot["last_seq"] == 4


async def test_last_message_at_is_the_time_of_the_latest_message(
    h: AiHarness,
) -> None:
    """The notebook shows 'Outdated' by comparing it with the snapshot."""
    chat = await h.new_chat()
    await h.say(chat.id, "one")
    h.clock.advance(minutes=30)
    await h.say(chat.id, "two")

    transcript = await h.services.public.chat_transcript(
        h.student.user_id, chat.id, None
    )

    assert transcript is not None
    assert transcript["last_message_at"] == h.clock.now()


async def test_another_owner_gets_nothing(h: AiHarness) -> None:
    """Chats are private: a stranger sees None, like a missing chat."""
    chat = await h.new_chat()
    await h.say(chat.id, "secret plan")

    stranger = await h.services.public.chat_transcript(
        h.other_student.user_id, chat.id, None
    )
    missing = await h.services.public.chat_transcript(h.student.user_id, uuid4(), None)

    assert stranger is None and missing is None


async def test_admin_and_deleted_chats_are_refused(h: AiHarness) -> None:
    """AI-12: Administration chats never become sources; deleted chats are gone."""
    admin_chat = await h.new_chat(assistant=Assistant.ADMIN)
    await h.say(admin_chat.id, "list the grades", actor=h.admin)
    student_chat = await h.new_chat()
    await h.say(student_chat.id, "hello")
    await h.services.delete_chat.execute(actor=h.student, chat_id=student_chat.id)

    admin = await h.services.public.chat_transcript(
        h.admin.user_id, admin_chat.id, None
    )
    deleted = await h.services.public.chat_transcript(
        h.student.user_id, student_chat.id, None
    )

    assert admin is None and deleted is None
