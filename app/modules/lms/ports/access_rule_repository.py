"""Port: audience rules of courses and steps (shared by authoring and learning)."""

from collections.abc import Iterable
from typing import Protocol
from uuid import UUID

from app.modules.lms.domain.access_rules import AccessRule


class AccessRuleRepository(Protocol):
    """Audience rules keyed by the course or step id; no row means public."""

    async def for_course(self, course_id: UUID) -> dict[UUID, AccessRule]:
        """Return the course rule (under the course id) and every step rule."""
        ...

    async def for_courses(
        self, course_ids: Iterable[UUID]
    ) -> dict[UUID, dict[UUID, AccessRule]]:
        """Return the course and step rules of each given course that has any."""
        ...

    async def delete_targets(self, course_id: UUID, target_ids: Iterable[UUID]) -> None:
        """Remove the rules of the given steps (or the course) of a course."""
        ...

    async def save(
        self, course_id: UUID, target_id: UUID, rule: AccessRule, updated_by: UUID
    ) -> None:
        """Store the rule; the public default removes the row."""
        ...

    async def lead(self, course_id: UUID) -> UUID | None:
        """Return the course lead: the first staff manager, else the founder."""
        ...
