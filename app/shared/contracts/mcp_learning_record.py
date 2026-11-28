"""What the learning-record MCP tools need (bootstrap/adapters/mcp_learning.py).

The caller's own course progress, submitted attempts, AI-review verdicts,
certificates and badges, plus the staff list of AI-review submissions of a block.
A missing id and someone else's id raise the same NotFoundError.
"""

from typing import Any, Protocol
from uuid import UUID

from app.shared.actor import Actor


class McpLearningRecordTools(Protocol):
    """The learning-record tools of the Students server and one LMS tool."""

    async def courses(self, actor: Actor) -> list[dict[str, Any]]:
        """Enrolled courses with progress, scores, certificate, badges, activity."""
        ...

    async def course_progress(self, actor: Actor, course_id: UUID) -> dict[str, Any]:
        """The mastery map of an enrolled course; not enrolled is not found."""
        ...

    async def my_attempts(
        self,
        actor: Actor,
        course_id: UUID,
        *,
        step_id: UUID | None,
        limit: int,
        cursor: str | None,
    ) -> dict[str, Any]:
        """`{"attempts": [...], "next_cursor"}`: submitted attempts, newest first."""
        ...

    async def my_attempt(self, actor: Actor, attempt_id: UUID) -> dict[str, Any]:
        """One submitted attempt; question texts only under the answers policy."""
        ...

    async def my_ai_reviews(
        self, actor: Actor, *, course_id: UUID | None, limit: int
    ) -> list[dict[str, Any]]:
        """The caller's AI-review sessions with a submission, newest first."""
        ...

    async def my_ai_review(self, actor: Actor, session_id: UUID) -> dict[str, Any]:
        """The final verdict of the caller's session; never the chat or files."""
        ...

    async def my_certificates(self, actor: Actor) -> dict[str, Any]:
        """`{"course": [...], "school": [...]}`: course and school certificates."""
        ...

    async def my_badges(self, actor: Actor) -> dict[str, Any]:
        """`{"earned": [...], "locked": [...]}` across enrolled courses."""
        ...

    async def ai_review_submissions(
        self,
        actor: Actor,
        course_id: UUID,
        step_id: UUID,
        block_id: str,
        *,
        limit: int,
    ) -> list[dict[str, Any]]:
        """Staff: reviewed sessions of a block with the verdict of each."""
        ...
