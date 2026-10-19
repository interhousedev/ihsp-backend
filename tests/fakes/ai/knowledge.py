"""Fakes of the knowledge ports of the assistants."""

from uuid import UUID

from app.shared.contracts.school_knowledge import KnowledgeEntry


class FakeKnowledgeLookup:
    """Answers with the queued entries (a fixed list) and records the queries."""

    def __init__(self, hits: list[KnowledgeEntry] | None = None) -> None:
        """Start with the entries every search returns."""
        self.hits = hits or []
        self.queries: list[tuple[str, int]] = []
        self.error: Exception | None = None

    async def search(self, query: str, *, limit: int = 5) -> list[KnowledgeEntry]:
        """Record the query and return the entries (or raise the set error)."""
        self.queries.append((query, limit))
        if self.error is not None:
            raise self.error
        return list(self.hits)


class FakeGapReporter:
    """Records the reports; may be told to fail."""

    def __init__(self) -> None:
        """Start empty."""
        self.reports: list[dict[str, object]] = []
        self.error: Exception | None = None

    async def report(
        self,
        query: str,
        *,
        chat_kind: str,
        chat_id: UUID | None,
        notebook_id: UUID | None,
        user_role: str,
    ) -> None:
        """Record the report (or raise the set error)."""
        if self.error is not None:
            raise self.error
        self.reports.append(
            {
                "query": query,
                "chat_kind": chat_kind,
                "chat_id": chat_id,
                "notebook_id": notebook_id,
                "user_role": user_role,
            }
        )
