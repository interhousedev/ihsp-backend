"""Port: attach the materials EMIS links to lessons (files, homework, videos)."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID

MaterialKind = Literal["classwork", "homework", "video"]


@dataclass(frozen=True, slots=True)
class EmisMaterial:
    """One address EMIS gives for a class: its topic file, homework file or video."""

    lesson_id: UUID
    url: str
    name: str  # the EMIS topic
    kind: MaterialKind


class LessonMaterialImporter(Protocol):
    """Adds EMIS materials to lessons, skipping those already attached."""

    async def import_materials(
        self, user_id: UUID, items: Sequence[EmisMaterial]
    ) -> int:
        """Attach the materials (downloads through the student's EMIS link)."""
        ...

    async def purge(self, lesson_ids: Sequence[UUID]) -> int:
        """Delete the lessons' EMIS materials and their stored files; return count."""
        ...

    async def lessons_with_materials(self, lesson_ids: Sequence[UUID]) -> set[UUID]:
        """The lessons that already have any resource attached."""
        ...
