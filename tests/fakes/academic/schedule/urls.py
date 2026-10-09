"""A LessonUrlImporter that remembers what EMIS attached, like the links module."""

from collections.abc import Sequence
from uuid import UUID

from app.shared.contracts.links import ImportedUrl


class FakeLessonUrls:
    """Keeps each (lesson, URL) once, even after a "deletion"."""

    def __init__(self) -> None:
        """Start with nothing attached."""
        self.attached: dict[tuple[UUID, str], ImportedUrl] = {}
        self.calls = 0

    async def import_lesson_urls(self, urls: Sequence[ImportedUrl]) -> int:
        """Attach the new URLs; return how many were new."""
        self.calls += 1
        new = 0
        for item in urls:
            key = (item.lesson_id, item.url)
            if key not in self.attached:
                self.attached[key] = item
                new += 1
        return new

    def of(self, lesson_id: UUID) -> list[ImportedUrl]:
        """The URLs attached to one lesson, oldest first."""
        return [item for (lid, _), item in self.attached.items() if lid == lesson_id]
