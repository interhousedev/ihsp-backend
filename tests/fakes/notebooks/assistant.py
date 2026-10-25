"""In-memory `NotebooksQueries` and `NotebooksCommands` for the assistant's tests."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from app.shared.actor import Actor
from app.shared.base_error import NotFoundError
from app.shared.ids import new_id

RESETS_AT = "2026-10-07T19:00:00+00:00"


@dataclass
class FakeSource:
    """A source of a fake notebook; ``passages`` are its texts in order."""

    title: str
    kind: str = "text"
    status: str = "ready"
    selected: bool = True
    passages: list[str] = field(default_factory=lambda: ["A passage."])
    id: UUID = field(default_factory=new_id)


@dataclass
class FakeNotebook:
    """A notebook of one owner."""

    owner_id: UUID
    title: str = "Biology"
    emoji: str | None = None
    summary: str | None = None
    key_topics: list[str] = field(default_factory=list)
    sources: list[FakeSource] = field(default_factory=list)
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    id: UUID = field(default_factory=new_id)


class FakeNotebooksQueries:
    """`NotebooksQueries` over notebooks added with `add`; every call is logged."""

    def __init__(self) -> None:
        """Start without notebooks and with an unused daily quota."""
        self.books: dict[UUID, FakeNotebook] = {}
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self.quota: dict[str, dict[str, Any]] = {
            "artifacts": {"used": 0, "limit": 20, "resets_at": RESETS_AT},
            "slides": {"used": 0, "limit": 6, "resets_at": RESETS_AT},
        }

    def add(self, book: FakeNotebook) -> FakeNotebook:
        """Register a notebook."""
        self.books[book.id] = book
        return book

    def _own(self, user_id: UUID, notebook_id: UUID) -> FakeNotebook | None:
        found = self.books.get(notebook_id)
        return found if found is not None and found.owner_id == user_id else None

    async def list_notebooks(
        self, user_id: UUID, limit: int = 20
    ) -> list[dict[str, Any]]:
        """Return the owner's notebooks."""
        self.calls.append(("list_notebooks", (user_id, limit)))
        return [
            {
                "id": str(b.id),
                "title": b.title,
                "emoji": b.emoji,
                "source_count": len(b.sources),
                "last_opened_at": None,
            }
            for b in self.books.values()
            if b.owner_id == user_id
        ][:limit]

    async def get_notebook(
        self, user_id: UUID, notebook_id: UUID
    ) -> dict[str, Any] | None:
        """Return the notebook or None when it is not the user's."""
        self.calls.append(("get_notebook", (user_id, notebook_id)))
        book = self._own(user_id, notebook_id)
        if book is None:
            return None
        return {
            "id": str(book.id),
            "title": book.title,
            "emoji": book.emoji,
            "summary": book.summary,
            "key_topics": list(book.key_topics),
            "source_count": len(book.sources),
            "sources": [
                {
                    "id": str(s.id),
                    "title": s.title,
                    "kind": s.kind,
                    "status": s.status,
                    "words": sum(len(p.split()) for p in s.passages),
                    "selected": s.selected,
                }
                for s in book.sources
            ],
        }

    async def search(
        self, user_id: UUID, notebook_id: UUID, query: str, limit: int = 8
    ) -> list[dict[str, Any]]:
        """Return the passages that contain the query, in source order."""
        self.calls.append(("search", (user_id, notebook_id, query, limit)))
        book = self._own(user_id, notebook_id)
        if book is None:
            return []
        rows = [
            {
                "source_id": str(s.id),
                "source_title": s.title,
                "seq": seq,
                "page": None,
                "text": text[:600],
            }
            for s in book.sources
            for seq, text in enumerate(s.passages, start=1)
            if query.lower() in text.lower()
        ]
        return rows[:limit]

    async def read_source_page(
        self, user_id: UUID, notebook_id: UUID, source_id: UUID, page: int
    ) -> dict[str, Any]:
        """Return a page (one passage per page) or raise a 404."""
        self.calls.append(("read_source_page", (user_id, notebook_id, source_id, page)))
        book = self._own(user_id, notebook_id)
        source = (
            next((s for s in book.sources if s.id == source_id), None) if book else None
        )
        if source is None or not 1 <= page <= len(source.passages):
            raise NotFoundError(support_details="source or page not found")
        return {
            "source_id": str(source.id),
            "title": source.title,
            "page": page,
            "pages": len(source.passages),
            "text": source.passages[page - 1],
        }

    async def list_artifacts(
        self, user_id: UUID, notebook_id: UUID
    ) -> list[dict[str, Any]]:
        """Return the outputs of the user's notebook."""
        self.calls.append(("list_artifacts", (user_id, notebook_id)))
        book = self._own(user_id, notebook_id)
        return list(book.artifacts) if book else []

    async def used_by_files(
        self, file_ids: Sequence[UUID]
    ) -> dict[UUID, list[tuple[str, UUID, str]]]:
        """Nothing uses a file."""
        self.calls.append(("used_by_files", (tuple(file_ids),)))
        return {}

    async def usage(self, user_id: UUID) -> dict[str, Any]:
        """Return the quota counters."""
        self.calls.append(("usage", (user_id,)))
        return {name: dict(part) for name, part in self.quota.items()}


class FakeNotebooksCommands:
    """`NotebooksCommands` that records calls and creates fake notebooks."""

    def __init__(self, queries: FakeNotebooksQueries) -> None:
        """Share the notebooks with the queries so created ones can be read back."""
        self.queries = queries
        self.created: list[dict[str, Any]] = []
        self.added: list[dict[str, Any]] = []
        self.requested: list[dict[str, Any]] = []
        self.reject_indexes: tuple[int, ...] = ()

    async def create_notebook(
        self, actor: Actor, title: str, sources: Sequence[dict[str, Any]]
    ) -> dict[str, Any]:
        """Create a notebook; the sources at ``reject_indexes`` are refused."""
        kept = [s for i, s in enumerate(sources) if i not in self.reject_indexes]
        book = self.queries.add(
            FakeNotebook(
                actor.user_id,
                title,
                sources=[
                    FakeSource(str(s.get("title") or s.get("file_id")), s["kind"])
                    for s in kept
                ],
            )
        )
        self.created.append(
            {"actor": actor, "title": title, "sources": list(sources), "id": book.id}
        )
        return {
            "id": str(book.id),
            "title": title,
            "added": len(kept),
            "rejected": [
                {"index": i, "type": "notebooks/source-duplicate"}
                for i in self.reject_indexes
            ],
        }

    async def add_sources(
        self, actor: Actor, notebook_id: UUID, sources: Sequence[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Add the sources to the actor's notebook."""
        book = self.queries.books.get(notebook_id)
        if book is None or book.owner_id != actor.user_id:
            raise NotFoundError(support_details="notebook not found")
        self.added.append(
            {"actor": actor, "notebook_id": notebook_id, "sources": list(sources)}
        )
        kept = [s for i, s in enumerate(sources) if i not in self.reject_indexes]
        return [
            {
                "id": str(new_id()),
                "kind": s["kind"],
                "title": str(s.get("title") or s.get("file_id")),
                "status": "pending",
            }
            for s in kept
        ]

    async def request_artifact(
        self,
        actor: Actor,
        notebook_id: UUID,
        kind: str,
        options: dict[str, Any],
        prompt: str | None,
    ) -> dict[str, Any]:
        """Queue an output and count it against the daily quota."""
        artifact_id = new_id()
        self.requested.append(
            {
                "actor": actor,
                "notebook_id": notebook_id,
                "kind": kind,
                "options": options,
                "prompt": prompt,
                "id": artifact_id,
            }
        )
        self.queries.quota["artifacts"]["used"] += 1
        return {"id": str(artifact_id), "kind": kind, "status": "queued"}
