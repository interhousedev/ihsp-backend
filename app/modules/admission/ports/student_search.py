"""Search over one student's own admission and study data (RAG for the AI tools)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID

StudentDataSource = Literal[
    "profile",
    "item",
    "essay",
    "task",
    "test_score",
    "document",
    "career",
    "list",
    "opportunity",
    "course",
    "grade",
]


@dataclass(frozen=True, slots=True)
class StudentDataHit:
    """One matching piece of the student's data, with a link back into the app."""

    source: StudentDataSource
    ref_id: str
    title: str
    snippet: str
    url_path: str
    score: float


class StudentDataSearch(Protocol):
    """Hybrid full-text plus vector search, always scoped to one student."""

    async def search(
        self,
        student_id: UUID,
        query: str,
        *,
        sources: tuple[StudentDataSource, ...] = (),
        limit: int = 8,
    ) -> list[StudentDataHit]:
        """Best hits first; an empty `sources` means every source."""
        ...

    async def reindex(self, student_id: UUID) -> int:
        """Rebuild the student's index; returns the number of indexed chunks."""
        ...

    async def forget(self, student_id: UUID) -> None:
        """Drop every indexed chunk of the student (erasure)."""
        ...
