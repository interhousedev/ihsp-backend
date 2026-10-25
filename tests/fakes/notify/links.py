"""A LinksApi that returns prepared lesson resources."""

from uuid import UUID

from app.shared.contracts.links import ResourceRef


class FakeLinksApi:
    """Lesson resources kept in a dictionary."""

    def __init__(self) -> None:
        """Start empty."""
        self.resources: dict[UUID, list[ResourceRef]] = {}

    async def lesson_resources(
        self, lesson_id: UUID, *, include_hidden: bool = False
    ) -> list[ResourceRef]:
        """Return the lesson's resources, hiding hidden ones unless asked."""
        items = self.resources.get(lesson_id, [])
        return [r for r in items if include_hidden or not r.hidden]
