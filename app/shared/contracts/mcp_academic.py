"""What the academic MCP tools need (implemented in bootstrap/adapters/mcp_academic.py).

Every method takes the user from the guard's actor, never from tool arguments. Someone
else's object raises a NotFoundError. Results are JSON-able.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Literal, Protocol
from uuid import UUID

from app.shared.actor import Actor

FetchReason = Literal["emis_reauth", "emis_busy", "old_term"]


@dataclass(frozen=True, slots=True)
class MaterialFetch:
    """State of a one-lesson EMIS materials fetch, shared by its classmates."""

    job_id: str
    status: Literal["running", "done", "failed"]
    started_at: datetime
    reason: FetchReason | None = None


class McpAcademicTools(Protocol):
    """Sync, teachers, GPA, lesson detail and the EMIS materials fallback."""

    async def request_refresh(self, actor: Actor) -> dict[str, Any]:
        """Start a self-service sync, or return the job and retry_after_seconds (D5)."""
        ...

    async def sync_status(self, user_id: UUID) -> dict[str, Any]:
        """The user's sync job; errors only as fixed codes, never raw text."""
        ...

    async def my_teachers(self, actor: Actor) -> list[dict[str, Any]]:
        """Teachers of the student's groups."""
        ...

    async def teacher_timetable(
        self, actor: Actor, teacher_id: UUID, start: date, end: date
    ) -> list[dict[str, Any]]:
        """Timetable of a teacher of this student; another teacher is not found."""
        ...

    async def gpa(self, user_id: UUID, semester: int | None) -> dict[str, Any]:
        """GPA as the platform calculates it, per-subject semester marks."""
        ...

    async def lesson_detail(self, actor: Actor, lesson_id: UUID) -> dict[str, Any]:
        """Lesson, homework, materials by kind, own mark and attendance."""
        ...

    async def teacher_names(self, teacher_ids: Sequence[UUID]) -> dict[UUID, str]:
        """Display names of the teachers of lessons the caller already sees."""
        ...

    async def start_material_fetch(
        self, user_id: UUID, lesson_id: UUID
    ) -> MaterialFetch:
        """Join or start the fetch of a lesson; the audience is checked by the tool."""
        ...

    async def material_fetch(self, lesson_id: UUID) -> MaterialFetch | None:
        """The fetch of a lesson, looked up by lesson and never by a client's job id."""
        ...


class LessonFetchStore(Protocol):
    """The shared state of the one-lesson fetches."""

    async def begin(
        self, lesson_id: UUID, user_id: UUID, fetch: MaterialFetch
    ) -> MaterialFetch | None:
        """Return the lesson's fetch, this one if none ran; None over the user's cap."""
        ...

    async def get(self, lesson_id: UUID) -> MaterialFetch | None:
        """Return the state, or None when no fetch is remembered."""
        ...

    async def finish(
        self, lesson_id: UUID, user_id: UUID, fetch: MaterialFetch
    ) -> None:
        """Store how the job ended, unless a newer job took the lesson."""
        ...
