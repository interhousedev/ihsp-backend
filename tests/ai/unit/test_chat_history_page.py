"""AiQueries.chat_history: one owner's chat, read page by page (MCP `get_chat`)."""

from uuid import uuid4

from tests.ai.conftest import AiHarness


async def test_owner_reads_the_chat_in_pages(h: AiHarness) -> None:
    """Pages follow seq; `next_after_seq` is set until the end."""
    chat = await h.new_chat()
    await h.say(chat.id, "one")
    await h.say(chat.id, "two")
    public = h.services.public

    first = await public.chat_history(h.student.user_id, chat.id, after_seq=0, limit=3)
    assert first is not None
    assert [m["seq"] for m in first["messages"]] == [1, 2, 3]
    assert first["next_after_seq"] == 3
    assert first["title"] == "one"
    assert first["messages"][0]["text"] == "one"
    assert first["messages"][0]["role"] == "user"

    rest = await public.chat_history(h.student.user_id, chat.id, after_seq=3, limit=3)
    assert rest is not None
    assert [m["seq"] for m in rest["messages"]] == [4]
    assert rest["next_after_seq"] is None


async def test_empty_chat_is_fine(h: AiHarness) -> None:
    """A chat without messages gives an empty page, not an error."""
    chat = await h.new_chat()

    page = await h.services.public.chat_history(
        h.student.user_id, chat.id, after_seq=0, limit=10
    )

    assert page is not None
    assert page["messages"] == []
    assert page["next_after_seq"] is None


async def test_another_users_unknown_and_admin_chats_are_not_found(
    h: AiHarness,
) -> None:
    """None for a foreign owner and for an id that does not exist."""
    chat = await h.new_chat()
    await h.say(chat.id, "secret")
    public = h.services.public

    assert (await public.chat_history(uuid4(), chat.id, after_seq=0, limit=10)) is None
    assert (
        await public.chat_history(h.student.user_id, uuid4(), after_seq=0, limit=10)
    ) is None
