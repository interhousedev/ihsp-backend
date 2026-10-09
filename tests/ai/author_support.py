"""The course author assistant arranged on fakes: a course, a step, a workspace."""

import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.modules.ai.application.views import ToolCallView, TurnResultView
from app.modules.ai.domain.assistant import Assistant
from app.shared.actor import Actor
from tests.ai.conftest import AiHarness
from tests.fakes.ai.author import (
    FakeCourse,
    FakeCourseWorld,
    FakeSection,
    FakeStep,
    FakeWorkspaceCommands,
    FakeWorkspaceNotebooks,
)
from tests.fakes.ai.llm import text_reply, tool_reply


@dataclass
class Author:
    """A teacher with ``edit`` on a course of one section and one step."""

    h: AiHarness
    world: FakeCourseWorld
    notebooks: FakeWorkspaceNotebooks
    commands: FakeWorkspaceCommands
    course: FakeCourse
    section: FakeSection
    step: FakeStep

    @property
    def teacher(self) -> Actor:
        """The course editor."""
        return self.h.teacher

    async def chat(self, course: FakeCourse | None = None) -> Any:
        """Start an author chat on the course."""
        return await self.h.services.create_chat.execute(
            actor=self.teacher,
            assistant=Assistant.LMS_AUTHOR,
            course_id=(course or self.course).id,
        )

    async def say(self, chat_id: UUID, text: str = "go") -> TurnResultView:
        """Send a message as the teacher."""
        return await self.h.say(chat_id, text, actor=self.teacher)

    async def run(
        self, name: str, args: dict[str, Any]
    ) -> tuple[ToolCallView, dict[str, Any]]:
        """Let the model call one read tool; return the call and what it got back."""
        chat = await self.chat()
        self.h.llm.push(tool_reply((name, args)), text_reply("ok"))
        result = await self.say(chat.id)
        sent = json.loads(self.h.llm.requests[-1]["messages"][-1]["content"])
        return result.new_messages[1].tool_calls[0], sent

    async def propose(
        self, name: str, args: dict[str, Any]
    ) -> tuple[UUID, ToolCallView]:
        """Let the model propose one write; return the chat and the card."""
        chat = await self.chat()
        self.h.llm.push(tool_reply((name, args)))
        result = await self.say(chat.id)
        return chat.id, result.new_messages[-1].tool_calls[0]

    async def approve(self, chat_id: UUID, call: ToolCallView) -> dict[str, Any]:
        """Approve a card; return the tool message the model receives."""
        self.h.llm.push(text_reply("Done."))
        await self.h.services.approve_tool_call.execute(
            actor=self.teacher, chat_id=chat_id, call_id=call.id
        )
        sent: dict[str, Any] = json.loads(
            self.h.llm.requests[-1]["messages"][-1]["content"]
        )
        return sent


def bind(h: AiHarness) -> tuple[FakeCourseWorld, FakeWorkspaceNotebooks, Any]:
    """Bind the fake LMS and notebooks to the assistant's late bindings."""
    world = FakeCourseWorld()
    notebooks = FakeWorkspaceNotebooks(world)
    commands = FakeWorkspaceCommands(notebooks)
    bindings = h.services.bindings
    bindings.lms_workspace = world
    bindings.lms_workspace_commands = world
    bindings.lms_queries = world  # type: ignore[assignment]
    bindings.lms_draft_commands = world  # type: ignore[assignment]
    bindings.notebooks = notebooks
    bindings.notebooks_commands = commands
    return world, notebooks, commands


def arrange(h: AiHarness) -> Author:
    """A course "Calculus" with the section "Limits" and the step "What is a limit"."""
    world, notebooks, commands = bind(h)
    course = world.add_course(h.teacher.user_id)
    section = world.add_section(course, "Limits")
    step = world.add_step(
        course,
        section,
        "What is a limit",
        {"type": "text", "markdown": "A limit is the value a function approaches."},
        {"type": "flashcards", "cards": [{"front": "lim", "back": "limit"}]},
    )
    return Author(h, world, notebooks, commands, course, section, step)
