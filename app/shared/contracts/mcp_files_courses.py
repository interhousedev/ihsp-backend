"""What the file catalog and learner tools need (bootstrap/adapters/mcp_files.py).

The actor comes from the guard. A file or course the actor may not see raises a
NotFoundError or returns None, exactly as for one that does not exist.
"""

from dataclasses import dataclass
from typing import Any, Literal, Protocol
from uuid import UUID

from app.shared.actor import Actor

FileOrigin = Literal[
    "personal", "shared", "lesson", "subject", "notebook", "flashcards", "course"
]


@dataclass(frozen=True, slots=True)
class VisibleFile:
    """A file the actor may read and why."""

    file_id: UUID
    origin: FileOrigin
    origin_id: UUID | None = None
    subject_id: UUID | None = None
    # A notebook file: "subject", "lms", "custom" or "shared".
    detail: str | None = None


class McpFilesCoursesTools(Protocol):
    """The catalog of files (B4) and enrolled course content (B5)."""

    async def visible_files(
        self,
        actor: Actor,
        *,
        only_personal: bool,
        origin: FileOrigin | None,
        subject_id: UUID | None,
        limit: int,
    ) -> list[VisibleFile]:
        """The files the actor may read, newest first."""
        ...

    async def resolve_file(self, actor: Actor, file_id: UUID) -> VisibleFile | None:
        """Why the actor may read this file; None when they may not."""
        ...

    async def search_visible_files(
        self, actor: Actor, query: str, *, only_personal: bool, limit: int
    ) -> dict[str, Any]:
        """Compute the allowed ids first and search within them, never filter after."""
        ...

    async def list_my_courses(self, actor: Actor) -> list[dict[str, Any]]:
        """Courses the actor is enrolled in."""
        ...

    async def course_curriculum(self, actor: Actor, course_id: UUID) -> dict[str, Any]:
        """Outline of an enrolled course; not enrolled is not found."""
        ...

    async def course_step(
        self, actor: Actor, course_id: UUID, step_id: UUID
    ) -> dict[str, Any]:
        """A step with no side effects and no questions or answers of tests."""
        ...

    async def issue_media_link(
        self, actor: Actor, course_id: UUID, step_id: UUID, block_id: str
    ) -> dict[str, Any]:
        """Rotate the one grant of (actor, block) and return its links and expiry."""
        ...
