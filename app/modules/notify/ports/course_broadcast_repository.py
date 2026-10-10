"""Storage port for the history of course broadcasts."""

from typing import Protocol
from uuid import UUID

from app.modules.notify.domain.course_broadcast import CourseBroadcast


class CourseBroadcastRepository(Protocol):
    """Writes and reads sent course broadcasts."""

    async def add(self, broadcast: CourseBroadcast) -> None:
        """Store one sent broadcast."""
        ...

    async def list_for_course(
        self, course_id: UUID, *, limit: int
    ) -> list[CourseBroadcast]:
        """Return the newest broadcasts of a course first."""
        ...
