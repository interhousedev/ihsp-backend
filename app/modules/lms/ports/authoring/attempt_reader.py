"""Port: read-only access to test attempts (MCP review tools)."""

from typing import Any, Protocol
from uuid import UUID


class AttemptReader(Protocol):
    """Reads attempts of a course; writing attempts belongs to the learning side."""

    async def recent_for_course(
        self, course_id: UUID, limit: int
    ) -> list[dict[str, Any]]:
        """Return the most recent attempts of a course as plain dicts."""
        ...
