"""LMS contracts (provider: lms module; consumer: MCP)."""

from typing import Any, Protocol
from uuid import UUID

from app.shared.actor import Actor


class LmsQueries(Protocol):
    """Read access to courses for authors."""

    async def courses_for_staff(
        self, user_id: UUID, permission: str
    ) -> list[dict[str, Any]]:
        """Return courses where the user holds the permission."""
        ...

    async def course_detail(self, course_id: UUID, actor: Actor) -> dict[str, Any]:
        """Return the course outline."""
        ...

    async def step_draft(self, step_id: UUID, actor: Actor) -> dict[str, Any]:
        """Return the draft content of a step."""
        ...

    async def pending_changes(self, course_id: UUID, actor: Actor) -> dict[str, Any]:
        """Return unpublished changes."""
        ...

    async def versions(self, course_id: UUID, actor: Actor) -> list[dict[str, Any]]:
        """Return published versions."""
        ...

    async def attempts(
        self, course_id: UUID, actor: Actor, limit: int = 50
    ) -> list[dict[str, Any]]:
        """Return recent attempts."""
        ...


class LmsDraftCommands(Protocol):
    """Add-only draft edits for MCP (MCP-6)."""

    async def create_section(
        self, actor: Actor, course_id: UUID, title: str, *, via_mcp: bool
    ) -> dict[str, Any]:
        """Add a section."""
        ...

    async def create_step(
        self,
        actor: Actor,
        course_id: UUID,
        section_id: str,
        title: str,
        *,
        via_mcp: bool,
    ) -> dict[str, Any]:
        """Add a step to a section."""
        ...

    async def add_block(
        self, actor: Actor, step_id: UUID, block: dict[str, Any], *, via_mcp: bool
    ) -> dict[str, Any]:
        """Add a block to a step."""
        ...

    async def add_question(
        self,
        actor: Actor,
        step_id: UUID,
        block_id: str,
        question: dict[str, Any],
        *,
        via_mcp: bool,
    ) -> dict[str, Any]:
        """Add a question to a test block."""
        ...
