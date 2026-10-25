"""A LessonMaterialImporter that remembers what EMIS attached, like the links module."""

from collections.abc import Sequence
from uuid import UUID

from app.modules.academic.application.schedule.ports.lesson_urls import EmisMaterial


class FakeLessonUrls:
    """Keeps each (lesson, URL) once, even after a "deletion"; a purge forgets them."""

    def __init__(self) -> None:
        """Start with nothing attached."""
        self.attached: dict[tuple[UUID, str], EmisMaterial] = {}
        self.calls = 0
        self.readers: list[UUID] = []
        self.purged: list[UUID] = []

    async def import_materials(
        self, user_id: UUID, items: Sequence[EmisMaterial]
    ) -> int:
        """Attach the new materials; return how many were new."""
        self.calls += 1
        self.readers.append(user_id)
        new = 0
        for item in items:
            key = (item.lesson_id, item.url)
            if key not in self.attached:
                self.attached[key] = item
                new += 1
        return new

    async def purge(self, lesson_ids: Sequence[UUID]) -> int:
        """Forget the materials of the lessons."""
        gone = [key for key in self.attached if key[0] in set(lesson_ids)]
        for key in gone:
            del self.attached[key]
        self.purged.extend(lesson_ids)
        return len(gone)

    async def lessons_with_materials(self, lesson_ids: Sequence[UUID]) -> set[UUID]:
        """The lessons that have something attached."""
        return {lid for lid, _ in self.attached} & set(lesson_ids)

    def of(self, lesson_id: UUID) -> list[EmisMaterial]:
        """The materials attached to one lesson, oldest first."""
        return [item for (lid, _), item in self.attached.items() if lid == lesson_id]
