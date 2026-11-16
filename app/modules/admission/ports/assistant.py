"""Ports of the admission assistant: the model, the thread store and the data."""

from typing import Any, Protocol
from uuid import UUID

from app.modules.admission.domain.assistant import Message, Thread
from app.shared.ai_tasks import AiTask


class AssistantModel(Protocol):
    """One model request with tools (OpenAI-style messages and tool definitions)."""

    async def turn(
        self,
        *,
        task: AiTask,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_tokens: int,
    ) -> dict[str, Any]:
        """Return `{text, tool_calls: [{id, name, arguments}], usage}`."""
        ...


class AssistantRepository(Protocol):
    """Threads and messages; every call is scoped to one student."""

    async def create_thread(self, thread: Thread) -> None:
        """Store a new thread."""
        ...

    async def get_thread(self, student_id: UUID, thread_id: UUID) -> Thread | None:
        """The student's thread, or None (also for another student's thread)."""
        ...

    async def list_threads(self, student_id: UUID, limit: int) -> list[Thread]:
        """The student's threads, latest first."""
        ...

    async def messages(self, student_id: UUID, thread_id: UUID) -> list[Message]:
        """The messages of the student's thread, oldest first."""
        ...

    async def append(self, student_id: UUID, messages: list[Message]) -> None:
        """Store messages and touch the thread's `updated_at`."""
        ...

    async def delete_thread(self, student_id: UUID, thread_id: UUID) -> bool:
        """Delete the student's thread with its messages; False when absent."""
        ...

    async def erase(self, student_id: UUID) -> tuple[int, int]:
        """Delete everything of the student; returns (threads, messages)."""
        ...


class AssistantData(Protocol):
    """Read-only views of one student's data, as plain JSON-ready dicts."""

    async def profile(self, student_id: UUID) -> dict[str, Any]:
        """Stage and filled profile answers."""
        ...

    async def tasks(self, student_id: UUID) -> list[dict[str, Any]]:
        """The student's tasks."""
        ...

    async def items(self, student_id: UUID) -> list[dict[str, Any]]:
        """Activities and honors."""
        ...

    async def test_scores(self, student_id: UUID) -> list[dict[str, Any]]:
        """Entered test scores."""
        ...

    async def deadlines(self, student_id: UUID) -> list[dict[str, Any]]:
        """Milestones of the student's university list."""
        ...

    async def universities(self, student_id: UUID) -> list[dict[str, Any]]:
        """The student's university list."""
        ...

    async def courses(self, student_id: UUID) -> list[dict[str, Any]]:
        """Courses with grades."""
        ...
