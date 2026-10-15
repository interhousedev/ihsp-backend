"""Chats and messages in PostgreSQL, and the approval flow on the SQL unit of work."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from app.modules.ai.application.views import TurnStatus
from app.modules.ai.domain.assistant import Assistant
from app.modules.ai.domain.chat import (
    Attachment,
    Chat,
    ChatMessage,
    ChatTier,
    Feedback,
    MessageContent,
    MessageRole,
)
from app.modules.ai.domain.chat_scope import ChatScope
from app.modules.ai.domain.tool_call import (
    PreviewData,
    PreviewField,
    ToolAccess,
    ToolCall,
    ToolStatus,
)
from app.modules.ai.infrastructure.uow import SqlAiUnitOfWork
from app.shared.ai_tasks import AiTask
from app.shared.db.uow_testing import noop_outbox_writer
from app.shared.ids import new_id
from app.shared.notifications import AuditDraft
from tests.ai.conftest import AiHarness, HarnessFactory
from tests.fakes.ai.llm import text_reply, tool_reply

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

NOW = datetime(2026, 10, 6, 9, 0, tzinfo=UTC)


@pytest.fixture
def audits() -> list[AuditDraft]:
    """Audit events written through the unit of work."""
    return []


@pytest.fixture
def sql_uow(
    sessionmaker_in_tx: async_sessionmaker[AsyncSession], audits: list[AuditDraft]
) -> Callable[[], SqlAiUnitOfWork]:
    """A factory of SQL units of work on the test transaction."""

    async def record(session: AsyncSession, drafts: list[AuditDraft]) -> None:
        audits.extend(drafts)

    return lambda: SqlAiUnitOfWork(sessionmaker_in_tx, noop_outbox_writer, record)


def make_chat(
    owner: object = None, assistant: Assistant = Assistant.STUDENT, **kw: object
) -> Chat:
    """A chat entity."""
    fields: dict[str, object] = {"title": "Title", **kw}
    return Chat(
        id=new_id(),
        owner_id=owner or new_id(),  # type: ignore[arg-type]
        assistant=assistant,
        model="anthropic/claude-haiku-5.5",
        last_message_at=NOW,
        **fields,  # type: ignore[arg-type]
    )


def make_message(chat: Chat, seq: int, role: MessageRole, **kw: object) -> ChatMessage:
    """A message entity."""
    return ChatMessage(
        id=new_id(),
        chat_id=chat.id,
        seq=seq,
        role=role,
        content=MessageContent(text=f"m{seq}"),
        created_at=NOW + timedelta(seconds=seq),
        **kw,  # type: ignore[arg-type]
    )


async def test_chat_round_trip(sql_uow: Callable[[], SqlAiUnitOfWork]) -> None:
    """AI-1: a chat is stored and changed field by field."""
    chat = make_chat()
    async with sql_uow() as uow:
        await uow.chats.add(chat)
        chat.title, chat.pending_approvals = "Renamed", 2
        await uow.chats.save(chat)
        await uow.commit()

    async with sql_uow() as uow:
        loaded = await uow.chats.get(chat.id)
        locked = await uow.chats.get_for_update(chat.id)
        assert loaded == locked == chat
        assert await uow.chats.get(new_id()) is None


async def test_message_with_tool_calls_round_trip(
    sql_uow: Callable[[], SqlAiUnitOfWork],
) -> None:
    """Models → ChatMessage: content, file_ids and the ToolCall JSON survive."""
    chat = make_chat()
    call = ToolCall(
        id="toolu_1",
        tool="create_flashcard_set",
        access=ToolAccess.WRITE,
        args={"title": "T"},
        status=ToolStatus.PENDING_APPROVAL,
        preview=PreviewData(
            title_key="ai-preview-create-flashcard-set",
            title_params={"title": "T", "count": 1},
            fields=[
                PreviewField(label_key="ai-field-title", value="T", sensitive=True)
            ],
            items=["a → b"],
        ),
        expires_at=NOW + timedelta(hours=24),
    )
    file_id = new_id()
    user = make_message(chat, 1, MessageRole.USER, file_ids=[file_id])
    user.content = MessageContent(
        text="hi", attachments=[Attachment(file_id=file_id, name="n.pdf")]
    )
    assistant = make_message(
        chat, 2, MessageRole.ASSISTANT, tool_calls=[call], tokens_in=10, tokens_out=3
    )
    async with sql_uow() as uow:
        await uow.chats.add(chat)
        await uow.messages.add(user)
        await uow.messages.add(assistant)
        await uow.commit()

    async with sql_uow() as uow:
        locked = await uow.messages.get_for_update(chat.id, 2)
        assert locked == assistant
        locked.tool_calls[0].status = ToolStatus.DONE
        locked.tool_calls[0].result = {"set_id": "x"}
        await uow.messages.save(locked)
        await uow.commit()

    async with sql_uow() as uow:
        tail = await uow.messages.list_tail(chat.id, 10)
        assert tail[0] == user
        assert tail[1].tool_calls[0].status is ToolStatus.DONE
        assert tail[1].tool_calls[0].result == {"set_id": "x"}
        assert await uow.messages.last_seq(chat.id) == 2
        assert await uow.messages.get_for_update(chat.id, 3) is None


async def test_tail_and_range_queries(sql_uow: Callable[[], SqlAiUnitOfWork]) -> None:
    """AI-9: the last N messages and a range, oldest first."""
    chat = make_chat()
    async with sql_uow() as uow:
        await uow.chats.add(chat)
        assert await uow.messages.last_seq(chat.id) == 0
        for seq in range(1, 8):
            await uow.messages.add(make_message(chat, seq, MessageRole.USER))
        await uow.commit()

    async with sql_uow() as uow:
        assert [m.seq for m in await uow.messages.list_tail(chat.id, 3)] == [5, 6, 7]
        rows = await uow.messages.list_range(chat.id, after_seq=2, up_to_seq=5)
        assert [m.seq for m in rows] == [3, 4, 5]
        rows = await uow.messages.list_range(chat.id, after_seq=5, up_to_seq=None)
        assert [m.seq for m in rows] == [6, 7]


async def test_chat_list_pagination_and_pending(
    sql_uow: Callable[[], SqlAiUnitOfWork],
) -> None:
    """AI-1: newest first with a (time, id) cursor; pending chats are found."""
    owner = new_id()
    chats = [make_chat(owner) for _ in range(3)]
    for index, chat in enumerate(chats):
        chat.last_message_at = NOW + timedelta(minutes=index)
    chats[0].pending_approvals = 1
    deleted = make_chat(owner, deleted_at=NOW)
    admin = make_chat(owner, assistant=Assistant.ADMIN)
    async with sql_uow() as uow:
        for chat in [*chats, deleted, admin]:
            await uow.chats.add(chat)
        await uow.commit()

    async with sql_uow() as uow:
        first = await uow.chats.list_for_owner(
            owner, Assistant.STUDENT, before=None, limit=2
        )
        cursor = (first[-1].last_message_at, first[-1].id)
        rest = await uow.chats.list_for_owner(
            owner, Assistant.STUDENT, before=cursor, limit=2
        )
        pending = await uow.chats.with_pending(owner)

    assert [c.id for c in first] == [chats[2].id, chats[1].id]
    assert [c.id for c in rest] == [chats[0].id]
    assert [c.id for c in pending] == [chats[0].id]


async def test_purge_removes_old_admin_chats_with_their_messages(
    sql_uow: Callable[[], SqlAiUnitOfWork],
) -> None:
    """AI-12: only old Administration chats go; their messages cascade."""
    old_admin = make_chat(assistant=Assistant.ADMIN)
    old_admin.last_message_at = NOW - timedelta(days=100)
    new_admin = make_chat(assistant=Assistant.ADMIN)
    old_student = make_chat()
    old_student.last_message_at = NOW - timedelta(days=100)
    async with sql_uow() as uow:
        for chat in (old_admin, new_admin, old_student):
            await uow.chats.add(chat)
        await uow.messages.add(make_message(old_admin, 1, MessageRole.USER))
        await uow.commit()

    async with sql_uow() as uow:
        removed = await uow.chats.purge_admin_chats(NOW - timedelta(days=90))
        await uow.commit()
        assert removed == 1
        assert await uow.chats.get(old_admin.id) is None
        assert await uow.messages.list_tail(old_admin.id, 5) == []
        assert await uow.chats.get(new_admin.id) is not None
        assert await uow.chats.get(old_student.id) is not None


async def test_approval_flow_on_the_sql_unit_of_work(
    make_harness: HarnessFactory,
    sql_uow: Callable[[], SqlAiUnitOfWork],
    audits: list[AuditDraft],
) -> None:
    """UF-WEB-20: propose, approve, continue — stored in PostgreSQL, audited."""
    h: AiHarness = make_harness(uow_factory=sql_uow)
    chat = await h.new_chat()
    cards = {"title": "Cells", "cards": [{"front": "Q", "back": "A"}]}
    h.llm.push(tool_reply(("create_flashcard_set", cards)), text_reply("Done!"))

    proposed = await h.say(chat.id, "cards please")
    call_id = proposed.new_messages[-1].tool_calls[0].id
    result = await h.services.approve_tool_call.execute(
        actor=h.student, chat_id=chat.id, call_id=call_id
    )

    detail = await h.services.get_chat.execute(actor=h.student, chat_id=chat.id)
    assert proposed.status is TurnStatus.AWAITING_APPROVAL
    assert result.status is TurnStatus.DONE
    assert [m.role for m in detail.messages] == ["user", "assistant"]
    assert detail.messages[1].tool_calls[0].status == "done"
    assert detail.chat.pending_approvals == 0 and detail.chat.title == "cards please"
    assert [a.type for a in audits] == ["ai.write_approved"]
    assert len(h.flashcards.create_calls) == 1


async def test_tier_and_feedback_round_trip(
    sql_uow: Callable[[], SqlAiUnitOfWork],
) -> None:
    """AI-1, AI-13: the tier is stored with the chat; the thumb with the message."""
    chat = make_chat(tier=ChatTier.SMART)
    plain = make_chat()
    answer = make_message(chat, 1, MessageRole.ASSISTANT)
    async with sql_uow() as uow:
        await uow.chats.add(chat)
        await uow.chats.add(plain)
        await uow.messages.add(answer)
        await uow.commit()

    async with sql_uow() as uow:
        smart, fast = await uow.chats.get(chat.id), await uow.chats.get(plain.id)
        assert smart is not None and smart.tier is ChatTier.SMART
        assert fast is not None and fast.tier is ChatTier.FAST
        locked = await uow.messages.get_for_update(chat.id, 1)
        assert locked is not None and locked.feedback is None
        locked.feedback, locked.feedback_comment = Feedback.DOWN, "too long"
        await uow.messages.set_feedback(locked)
        await uow.commit()

    async with sql_uow() as uow:
        rated = await uow.messages.get_for_update(chat.id, 1)
        assert rated is not None
        assert (rated.feedback, rated.feedback_comment) == (Feedback.DOWN, "too long")
        rated.feedback, rated.feedback_comment = Feedback.UP, None
        await uow.messages.set_feedback(rated)
        await uow.commit()

    async with sql_uow() as uow:
        again = await uow.messages.get_for_update(chat.id, 1)
        assert again is not None
        assert (again.feedback, again.feedback_comment) == (Feedback.UP, None)


async def test_saving_a_message_keeps_its_feedback(
    sql_uow: Callable[[], SqlAiUnitOfWork],
) -> None:
    """AI-1: tool-call saves never overwrite a thumb given in the meantime."""
    chat = make_chat()
    answer = make_message(chat, 1, MessageRole.ASSISTANT)
    async with sql_uow() as uow:
        await uow.chats.add(chat)
        await uow.messages.add(answer)
        await uow.commit()
    async with sql_uow() as uow:
        stale = await uow.messages.get_for_update(chat.id, 1)
        assert stale is not None
        rated = stale
        rated.feedback = Feedback.UP
        await uow.messages.set_feedback(rated)
        older = make_message(chat, 1, MessageRole.ASSISTANT)
        older.id, older.tokens_in = answer.id, 7
        await uow.messages.save(older)
        await uow.commit()

    async with sql_uow() as uow:
        loaded = await uow.messages.get_for_update(chat.id, 1)
        assert loaded is not None
        assert (loaded.feedback, loaded.tokens_in) == (Feedback.UP, 7)


async def test_delete_after_removes_only_the_later_messages(
    sql_uow: Callable[[], SqlAiUnitOfWork],
) -> None:
    """AI-2: regenerate deletes everything above the last user message."""
    chat = make_chat()
    other = make_chat()
    async with sql_uow() as uow:
        await uow.chats.add(chat)
        await uow.chats.add(other)
        for seq in range(1, 6):
            await uow.messages.add(make_message(chat, seq, MessageRole.USER))
        await uow.messages.add(make_message(other, 1, MessageRole.USER))
        await uow.commit()

    async with sql_uow() as uow:
        removed = await uow.messages.delete_after(chat.id, 3)
        again = await uow.messages.delete_after(chat.id, 3)
        await uow.messages.add(make_message(chat, 4, MessageRole.ASSISTANT))
        await uow.commit()

    async with sql_uow() as uow:
        rows = await uow.messages.list_tail(chat.id, 10)
        assert (removed, again) == (2, 0)
        assert [(m.seq, m.role) for m in rows][-2:] == [
            (3, MessageRole.USER),
            (4, MessageRole.ASSISTANT),
        ]
        assert len(await uow.messages.list_tail(other.id, 10)) == 1


async def test_title_search_treats_like_wildcards_as_text(
    sql_uow: Callable[[], SqlAiUnitOfWork],
) -> None:
    """AI-1: `%`, `_` and a backslash are literal; any letter case matches."""
    owner = new_id()
    titles = ["100% sure", "1000 sure", "snake_case", "snakexcase", "C:\\temp"]
    titles += ["Biology exam", "Помощь по Биологии"]
    chats = {t: make_chat(owner, title=t) for t in titles}
    for index, chat in enumerate(chats.values()):
        chat.last_message_at = NOW + timedelta(minutes=index)
    stranger = make_chat(title="Biology of someone else")
    admin = make_chat(owner, assistant=Assistant.ADMIN, title="Biology admin")
    async with sql_uow() as uow:
        for chat in [*chats.values(), stranger, admin]:
            await uow.chats.add(chat)
        await uow.commit()

    async def found(query: str) -> list[str]:
        async with sql_uow() as uow:
            rows = await uow.chats.list_for_owner(
                owner, Assistant.STUDENT, before=None, limit=20, title_contains=query
            )
        return [c.title for c in rows]

    assert await found("%") == ["100% sure"]
    assert await found("e_c") == ["snake_case"]
    assert await found("\\") == ["C:\\temp"]
    assert await found("BIOLOGY") == ["Biology exam"]
    assert await found("биолог") == ["Помощь по Биологии"]
    assert await found("nothing") == []


async def test_title_search_pages_with_the_cursor(
    sql_uow: Callable[[], SqlAiUnitOfWork],
) -> None:
    """AI-1: the filter and the (time, id) cursor work together."""
    owner = new_id()
    chats = [make_chat(owner, title=f"Biology {n}") for n in range(4)]
    for index, chat in enumerate(chats):
        chat.last_message_at = NOW + timedelta(minutes=index)
    async with sql_uow() as uow:
        for chat in [*chats, make_chat(owner, title="Chemistry")]:
            await uow.chats.add(chat)
        await uow.commit()

    async with sql_uow() as uow:
        first = await uow.chats.list_for_owner(
            owner, Assistant.STUDENT, before=None, limit=2, title_contains="bio"
        )
        rest = await uow.chats.list_for_owner(
            owner,
            Assistant.STUDENT,
            before=(first[-1].last_message_at, first[-1].id),
            limit=2,
            title_contains="bio",
        )

    assert [c.id for c in first] == [chats[3].id, chats[2].id]
    assert [c.id for c in rest] == [chats[1].id, chats[0].id]


async def test_regenerate_and_feedback_on_the_sql_unit_of_work(
    make_harness: HarnessFactory,
    sql_uow: Callable[[], SqlAiUnitOfWork],
) -> None:
    """AI-2: rate, regenerate and reload — stored in PostgreSQL, same seq reused."""
    h: AiHarness = make_harness(uow_factory=sql_uow)
    chat = await h.services.create_chat.execute(
        actor=h.student, assistant=Assistant.STUDENT, tier=ChatTier.SMART
    )
    h.llm.push(tool_reply(("get_my_subjects", {})), text_reply("Old answer"))
    await h.say(chat.id, "my subjects")
    await h.services.set_message_feedback.execute(
        actor=h.student,
        chat_id=chat.id,
        seq=2,
        rating=Feedback.DOWN,
        comment="wrong",
    )
    h.llm.push(text_reply("New answer"))

    result = await h.services.regenerate_answer.execute(
        actor=h.student, chat_id=chat.id
    )

    detail = await h.services.get_chat.execute(actor=h.student, chat_id=chat.id)
    assert [(m.seq, m.role, m.text) for m in result.new_messages] == [
        (2, "assistant", "New answer")
    ]
    assert [(m.seq, m.text, m.feedback) for m in detail.messages] == [
        (1, "my subjects", None),
        (2, "New answer", None),
    ]
    assert detail.chat.tier == "smart"
    assert (
        h.llm.requests[-1]["model"]
        == h.settings.ai_profile(AiTask.STUDENT_CHAT_SMART).model
    )


async def test_author_chat_scope_round_trip_and_course_filter(
    sql_uow: Callable[[], SqlAiUnitOfWork],
) -> None:
    """An lms_author chat keeps its course scope; the list filters by course."""
    owner, course, other = new_id(), new_id(), new_id()
    mine = make_chat(
        owner,
        Assistant.LMS_AUTHOR,
        scope=ChatScope(course_id=course, notebook_id=new_id()),
    )
    elsewhere = make_chat(
        owner,
        Assistant.LMS_AUTHOR,
        scope=ChatScope(course_id=other, notebook_id=new_id()),
    )
    async with sql_uow() as uow:
        await uow.chats.add(mine)
        await uow.chats.add(elsewhere)
        await uow.commit()

    async with sql_uow() as uow:
        loaded = await uow.chats.get(mine.id)
        listed = await uow.chats.list_for_owner(
            owner, Assistant.LMS_AUTHOR, before=None, limit=10, course_id=course
        )

    assert loaded == mine and loaded is not None and loaded.course_id == course
    assert [c.id for c in listed] == [mine.id]
