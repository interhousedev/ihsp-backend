"""AI-STEPS: the notebook chat streams its steps and stores them with the answer."""

from collections.abc import AsyncIterator
from typing import Any

from app.modules.notebooks.wiring_chat import ChatServices
from app.modules.notebooks.wiring_core import NotebooksCore
from app.shared.actor import Actor
from app.shared.agent_steps import StepKind, record_step, step
from tests.fakes.notebooks.llm import ScriptedLlm
from tests.notebooks.unit.chat.support import (
    collect,
    names,
    notebook_with_source,
    thread,
)


class SteppingLlm(ScriptedLlm):
    """Emits a retrieval hop while it streams, as a pipeline stage would."""

    async def stream(self, **kwargs: Any) -> AsyncIterator[dict[str, Any]]:
        self.calls += 1
        async with step(StepKind.RETRIEVE, "Searched the sources", target="hop 1"):
            pass
        yield {"delta": "Fact [[S1:P1]]."}
        record_step(StepKind.THINK, "Checked the answer")
        yield {"delta": " Done."}


async def test_steps_stream_live_and_are_stored(
    core: NotebooksCore, chat: ChatServices, student: Actor, scripted_llm: ScriptedLlm
) -> None:
    """AI-STEPS: `step` events come between `message` and `done`, then are stored."""
    notebook, _ = await notebook_with_source(core, student)
    scripted_llm.__class__ = SteppingLlm

    events = await collect(chat.ask_notebook.stream(student, notebook.id, "Q?"))

    kinds = names(events)
    assert kinds[0] == "message" and kinds[-1] == "done"
    updates = [e.data for e in events if e.name == "step"]
    assert [(u["kind"], u["status"]) for u in updates] == [
        ("retrieve", "running"),
        ("retrieve", "done"),
        ("think", "done"),
    ]
    done = events[-1].data["message"]
    assert [s["label"] for s in done["steps"]] == [
        "Searched the sources",
        "Checked the answer",
    ]
    stored = await thread(core, student, notebook)
    assert [s.kind for s in stored[-1].content.steps] == [
        StepKind.RETRIEVE,
        StepKind.THINK,
    ]
    assert stored[0].content.steps == []


async def test_steps_are_not_sent_back_to_the_model(
    core: NotebooksCore, chat: ChatServices, student: Actor, scripted_llm: ScriptedLlm
) -> None:
    """AI-STEPS: the next question's history carries no step labels."""
    notebook, _ = await notebook_with_source(core, student)
    scripted_llm.__class__ = SteppingLlm
    await collect(chat.ask_notebook.stream(student, notebook.id, "Q1?"))
    scripted_llm.__class__ = ScriptedLlm
    scripted_llm.queue_stream(["Fine."])

    await collect(chat.ask_notebook.stream(student, notebook.id, "Q2?"))

    assert "Searched the sources" not in str(scripted_llm.stream_requests[-1])
