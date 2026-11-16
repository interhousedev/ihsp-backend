"""Ports under the student data search: chunk storage and chunk collection."""

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.modules.admission.domain.student_chunks import Chunk
from app.modules.admission.ports.student_search import StudentDataSource


class ChunkStore(Protocol):
    """Indexed chunks; every call is scoped to one student."""

    async def replace(
        self, student_id: UUID, chunks: Sequence[Chunk], now: datetime
    ) -> int:
        """Make the stored chunks exactly `chunks`; returns how many are stored."""
        ...

    async def delete(self, student_id: UUID) -> None:
        """Drop every chunk of the student and the vectors no other row uses."""
        ...

    async def ref_count(self, student_id: UUID) -> int:
        """How many distinct rows (source, ref_id) are indexed."""
        ...

    async def indexed_at(self, student_id: UUID) -> datetime | None:
        """When the student was last indexed; None when never (or forgotten)."""
        ...

    async def text_search(
        self,
        student_id: UUID,
        tokens: Sequence[str],
        sources: Sequence[StudentDataSource],
        limit: int,
    ) -> list[Chunk]:
        """Chunks that contain any token (prefix match), best first."""
        ...

    async def vector_search(
        self,
        student_id: UUID,
        model: str,
        vector: Sequence[float],
        sources: Sequence[StudentDataSource],
        limit: int,
    ) -> list[Chunk]:
        """Chunks nearer than `MAX_VECTOR_DISTANCE` to the vector, nearest first."""
        ...


class ChunkCollector(Protocol):
    """Reads one student's data from the module's tables and other modules."""

    async def collect(self, student_id: UUID) -> list[Chunk]:
        """Every chunk of the student's current data."""
        ...

    async def ref_count(self, student_id: UUID) -> int:
        """How many distinct rows (source, ref_id) `collect` yields."""
        ...

    async def latest_change(self, student_id: UUID) -> datetime | None:
        """The newest update time of the student's data; None when there is none."""
        ...
