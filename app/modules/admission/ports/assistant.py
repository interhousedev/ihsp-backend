"""The assistant's read-only view of one student's data."""

from typing import Any, Protocol
from uuid import UUID


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

    async def memory_notes(self, student_id: UUID) -> list[dict[str, Any]]:
        """Notes the student saved for the assistant (newest first)."""
        ...

    async def essays(self, student_id: UUID) -> list[dict[str, Any]]:
        """Essays without their text."""
        ...

    async def documents(self, student_id: UUID) -> list[dict[str, Any]]:
        """Metadata of the student's non-confidential documents."""
        ...
