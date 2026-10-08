"""AiQueries for other modules: shares and the pending-approval alert (SHR, WEB-2)."""

from app.modules.ai.domain.assistant import Assistant
from tests.ai.conftest import AiHarness
from tests.fakes.ai.llm import text_reply, tool_reply

CARDS = {"title": "Cells", "cards": [{"front": "Q", "back": "A"}]}


async def test_shared_chat_hides_tool_results_and_keeps_notes(h: AiHarness) -> None:
    """AI-12, SHR: share pages get texts and "Looked up…" notes, never results."""
    h.marks.summary = []
    chat = await h.new_chat()
    h.llm.push(tool_reply(("get_my_subjects", {})), text_reply("You have no subjects."))
    await h.say(chat.id, "What do I study?")

    shared = await h.services.public.chat_for_share(chat.id, None)

    assert shared is not None
    assert shared["owner_id"] == h.student.user_id
    assert [m["role"] for m in shared["messages"]] == ["user", "assistant", "assistant"]
    assert shared["messages"][1]["tool_notes"] == ["Looked up your subjects"]
    assert shared["messages"][2]["text"] == "You have no subjects."
    assert "result" not in str(shared)


async def test_shared_chat_snapshot_stops_at_a_message(h: AiHarness) -> None:
    """SHR-1: a snapshot covers the messages up to `until_seq`."""
    chat = await h.new_chat()
    await h.say(chat.id, "one")
    await h.say(chat.id, "two")

    shared = await h.services.public.chat_for_share(chat.id, 2)

    assert shared is not None
    assert [m["text"] for m in shared["messages"]] == ["one", "ok"]


async def test_deleted_and_admin_chats_cannot_be_shared(h: AiHarness) -> None:
    """AI-12: no share for Administration chats or deleted chats."""
    student_chat = await h.new_chat()
    admin_chat = await h.new_chat(assistant=Assistant.ADMIN)
    await h.services.delete_chat.execute(actor=h.student, chat_id=student_chat.id)

    assert await h.services.public.chat_for_share(student_chat.id, None) is None
    assert await h.services.public.chat_for_share(admin_chat.id, None) is None
    assert await h.services.public.chat_owner(student_chat.id) is None
    assert await h.services.public.chat_owner(admin_chat.id) == h.admin.user_id


async def test_pending_approvals_sum_over_chats(h: AiHarness) -> None:
    """WEB-2: the Today alert counts waiting approval cards of all chats."""
    for _ in range(2):
        chat = await h.new_chat()
        h.llm.push(tool_reply(("create_flashcard_set", CARDS)))
        await h.say(chat.id, "cards")

    assert await h.services.public.pending_approvals(h.student.user_id) == 2
    assert await h.services.public.pending_approvals(h.other_student.user_id) == 0


async def test_detail_flags_a_chat_with_a_live_share(h: AiHarness) -> None:
    """UF-WEB-24: `shared` is true when the links module reports a live share."""

    class Lookup:
        async def is_shared(self, chat_id: object) -> bool:
            return True

    chat = await h.new_chat()
    before = await h.services.get_chat.execute(actor=h.student, chat_id=chat.id)
    h.services.bindings.share_lookup = Lookup()  # type: ignore[assignment]
    after = await h.services.get_chat.execute(actor=h.student, chat_id=chat.id)

    assert (before.shared, after.shared) == (False, True)
