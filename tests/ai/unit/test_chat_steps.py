"""AI-STEPS: tool calls of an AI chat answer become steps stored with the message."""

import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from app.modules.ai.application.tool_runner import ToolRunner, step_kind_for
from app.modules.ai.application.tools.base import ReadTool, ToolContext
from app.modules.ai.application.tools.registry import ToolRegistry
from app.modules.ai.domain.assistant import Assistant
from app.modules.ai.domain.chat import ChatMessage, MessageContent, MessageRole
from app.modules.ai.domain.history import to_llm_messages
from app.modules.ai.domain.tool_args import ToolArgs
from app.shared.actor import Actor, Role
from app.shared.agent_steps import StepKind, StepRecorder, StepStatus, recording
from tests.ai.conftest import AiHarness
from tests.fakes.ai.llm import text_reply, tool_reply
from tests.fakes.clock import FixedClock


class FileArgs(ToolArgs):
    """A file id."""

    file_id: str


class ReadFile(ReadTool[FileArgs]):
    """Returns a named file."""

    name = "read_file"
    description = "read"
    args_model = FileArgs

    async def run(self, args: FileArgs, ctx: ToolContext) -> dict[str, Any]:
        return {"name": "Essay.docx", "text": "..."}


def _ctx() -> ToolContext:
    actor = Actor(user_id=uuid4(), roles=frozenset({Role.STUDENT}))
    return ToolContext(actor=actor, chat_id=uuid4(), locale="en")


async def test_read_calls_are_recorded_as_steps() -> None:
    """AI-STEPS: a read tool call is one step with its file name as the target."""
    runner = ToolRunner(ToolRegistry(student=[ReadFile()], admin=[]), FixedClock())
    recorder = StepRecorder()
    with recording(recorder):
        await runner.propose(
            Assistant.STUDENT,
            _ctx(),
            [
                {"id": "a", "name": "read_file", "arguments": {"file_id": "f1"}},
                {"id": "b", "name": "nope", "arguments": {}},
            ],
            set(),
        )
    steps = recorder.steps
    assert [(s.kind, s.label, s.status) for s in steps] == [
        (StepKind.READ_FILE, "read_file", StepStatus.DONE),
        (StepKind.TOOL, "nope", StepStatus.FAILED),
    ]
    assert steps[0].target == "Essay.docx"
    assert steps[0].ref == "a"


async def test_runner_without_recorder_still_works() -> None:
    """AI-STEPS: emitting steps is optional."""
    runner = ToolRunner(ToolRegistry(student=[ReadFile()], admin=[]), FixedClock())
    calls = await runner.propose(
        Assistant.STUDENT,
        _ctx(),
        [{"id": "a", "name": "read_file", "arguments": {"file_id": "f1"}}],
        set(),
    )
    assert len(calls) == 1


def test_kind_follows_the_tool_name() -> None:
    """AI-STEPS: the icon of a step comes from the kind of tool."""
    assert step_kind_for("read_notebook_source") is StepKind.READ_FILE
    assert step_kind_for("search_workspace") is StepKind.RETRIEVE
    assert step_kind_for("create_flashcard_set") is StepKind.CREATE
    assert step_kind_for("make_document") is StepKind.CREATE
    assert step_kind_for("get_schedule") is StepKind.TOOL


def test_steps_are_not_sent_back_to_the_model() -> None:
    """AI-STEPS: the history the model sees has no trace of the steps."""
    recorder = StepRecorder()
    recorder.add(StepKind.WEB_SEARCH, "Searched the web", target="SECRET-STEP")
    answer = ChatMessage(
        id=uuid4(),
        chat_id=uuid4(),
        seq=2,
        role=MessageRole.ASSISTANT,
        content=MessageContent(text="hi", steps=recorder.steps),
        created_at=datetime.now(UTC),
    )
    question = ChatMessage(
        id=uuid4(),
        chat_id=answer.chat_id,
        seq=1,
        role=MessageRole.USER,
        content=MessageContent(text="q"),
        created_at=datetime.now(UTC),
    )
    sent = to_llm_messages([question, answer])
    assert "SECRET-STEP" not in str(sent)
    stored = MessageContent.model_validate(answer.content.model_dump(mode="json"))
    assert stored.steps[0].target == "SECRET-STEP"


async def test_a_turn_stores_its_steps_with_the_answers(h: AiHarness) -> None:
    """AI-STEPS: the search and each tool call are stored, in order, on the answers."""
    chat = await h.new_chat()
    h.llm.push(tool_reply(("get_my_subjects", {})), text_reply("Done [[W1]]"))

    result = await h.say(chat.id, "my subjects and photosynthesis", web=True)

    (answer,) = result.new_messages[1:]
    assert [(s.kind, s.label) for s in answer.steps] == [
        (StepKind.WEB_SEARCH, "Searched the web"),
        (StepKind.TOOL, "get_my_subjects"),
    ]
    stored = h.store.chat_messages(chat.id)
    assert [len(m.content.steps) for m in stored] == [0, 2]
    assert "Searched the web" not in json.dumps(h.llm.requests[-1]["messages"])
