"""In-memory StudentDataSearch: hits per student, any query word as a substring."""

from uuid import UUID

from app.modules.admission.ports.student_search import (
    StudentDataHit,
    StudentDataSource,
)


class FakeStudentSearch:
    """Returns only the asked student's hits that match the query or the filter."""

    def __init__(self, hits: dict[UUID, list[StudentDataHit]] | None = None) -> None:
        self.hits = hits or {}
        self.calls: list[tuple[UUID, str, tuple[str, ...]]] = []
        self.reindexed: list[UUID] = []

    async def search(
        self,
        student_id: UUID,
        query: str,
        *,
        sources: tuple[StudentDataSource, ...] = (),
        limit: int = 8,
    ) -> list[StudentDataHit]:
        self.calls.append((student_id, query, sources))
        words = query.casefold().split()
        found = [
            h
            for h in self.hits.get(student_id, [])
            if (not sources or h.source in sources)
            and (
                not words
                or any(w in f"{h.title} {h.snippet}".casefold() for w in words)
            )
        ]
        return sorted(found, key=lambda h: -h.score)[:limit]

    async def reindex(self, student_id: UUID) -> int:
        self.reindexed.append(student_id)
        return len(self.hits.get(student_id, []))

    async def forget(self, student_id: UUID) -> None:
        self.hits.pop(student_id, None)
