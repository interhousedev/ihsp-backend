"""Port: attach web addresses from EMIS to lessons (implemented by the links module)."""

from collections.abc import Sequence
from typing import Protocol

from app.shared.contracts.links import ImportedUrl


class LessonUrlImporter(Protocol):
    """Adds URLs as lesson materials, skipping those already attached."""

    async def import_lesson_urls(self, urls: Sequence[ImportedUrl]) -> int:
        """Attach the URLs; return how many were new."""
        ...
