"""AI-EFF-1/2/3: a long notebook chat sends the last N messages and a cached summary."""

from app.modules.notebooks.domain.compaction import SUMMARY_HEAD
from app.modules.notebooks.domain.enums import MessageRole
from app.modules.notebooks.wiring_chat import build_chat
from app.shared.actor import Actor
from app.shared.ai_tasks import COMPACT_MODEL
from tests.factories.notebooks import make_message
from tests.fakes.notebooks.llm import ScriptedLlm
from tests.notebooks.unit.chat.support import (
    ANSWER,
    CoreFactory,
    last_message,
    notebook_with_source,
)


async def test_a_long_chat_is_compacted_in_the_request(
    make_core: CoreFactory, student: Actor, scripted_llm: ScriptedLlm
) -> None:
    """AI-EFF-2/3: sources (cached), summary, the last 4 messages, the question."""
    core = make_core(limits={"ai_chat_history_limit": 4})
    notebook, _ = await notebook_with_source(core, student)
    for seq in range(1, 31):
        role = MessageRole.USER if seq % 2 else MessageRole.ASSISTANT
        await make_message(core.uow_factory, notebook, role=role, text=f"m{seq}")
    scripted_llm.queue_text("the student asked about cells")
    scripted_llm.queue_text(ANSWER)

    await build_chat(core).ask_notebook.execute(student, notebook.id, "Next?")

    compact, answer = scripted_llm.text_requests[-2:]
    assert compact["model"] == COMPACT_MODEL
    messages = answer["messages"]
    assert [m["content"] for m in messages[1:-1]] == ["m27", "m28", "m29", "m30"]
    assert last_message(answer) == "Next?"
    first = messages[0]["content"]
    assert first[0]["cache_control"] == {"type": "ephemeral"}
    assert first[1]["text"].startswith(SUMMARY_HEAD)
    assert "the student asked about cells" in first[1]["text"]


async def test_a_short_chat_makes_no_compaction_call(
    make_core: CoreFactory, student: Actor, scripted_llm: ScriptedLlm
) -> None:
    """AI-EFF-3: under the limit the thread goes whole and no summary is asked for."""
    core = make_core()
    notebook, _ = await notebook_with_source(core, student)
    await make_message(core.uow_factory, notebook, text="m1")
    await make_message(
        core.uow_factory, notebook, role=MessageRole.ASSISTANT, text="m2"
    )
    scripted_llm.queue_text(ANSWER)

    await build_chat(core).ask_notebook.execute(student, notebook.id, "Next?")

    assert len(scripted_llm.text_requests) == 1
    assert len(scripted_llm.text_requests[0]["messages"]) == 4
