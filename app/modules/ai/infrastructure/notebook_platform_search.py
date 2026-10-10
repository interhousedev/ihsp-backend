"""Platform search over the notebooks the user can read (via NotebooksQueries)."""

from collections.abc import Sequence
from uuid import UUID

from app.modules.ai.application.late_bindings import LateBindings
from app.shared.actor import Actor
from app.shared.contracts.web_search import PlatformPassage, PlatformSearch

NOTEBOOKS = 8


class NotebookPlatformSearch:
    """Implements `PlatformSearch` over the user's accessible notebook sources."""

    def __init__(self, bindings: LateBindings) -> None:
        """Store the late-bound notebooks API."""
        self.bindings = bindings

    async def search(
        self, actor: Actor, query: str, limit: int
    ) -> list[PlatformPassage]:
        """Passages of the user's notebooks (none while notebooks are unbound)."""
        api = self.bindings.notebooks
        if api is None:
            return []
        found: list[PlatformPassage] = []
        for nb in await api.list_notebooks(actor.user_id, NOTEBOOKS):
            rows = await api.search(actor.user_id, UUID(nb["id"]), query, limit)
            for r in rows:
                found.append(
                    PlatformPassage(
                        title=r["source_title"] or nb["title"],
                        url=f"/notebooks/{nb['id']}?source={r['source_id']}",
                        text=r["text"],
                        ref_kind="notebook_source",
                        ref_id=str(r["source_id"]),
                    )
                )
        return found[:limit]


class LateLibrarySearch:
    """The library search bound after the module is built (empty until then)."""

    def __init__(self, bindings: LateBindings) -> None:
        """Store the bindings."""
        self.bindings = bindings

    async def search(
        self, actor: Actor, query: str, limit: int
    ) -> list[PlatformPassage]:
        """Library passages, or none while unbound."""
        inner = self.bindings.library_search
        return await inner.search(actor, query, limit) if inner else []


class LateSharedSearch:
    """The shared-passage search bound after notebooks is built (empty until then)."""

    def __init__(self, bindings: LateBindings) -> None:
        """Store the bindings."""
        self.bindings = bindings

    async def search(
        self, actor: Actor, query: str, limit: int
    ) -> list[PlatformPassage]:
        """Shared passages the actor may read, or none while unbound."""
        inner = self.bindings.shared_search
        return await inner.search(actor, query, limit) if inner else []


class CompositePlatformSearch:
    """Merges several platform searches and drops passages seen twice."""

    def __init__(self, parts: Sequence[PlatformSearch]) -> None:
        """Store the searches, in priority order."""
        self.parts = parts

    async def search(
        self, actor: Actor, query: str, limit: int
    ) -> list[PlatformPassage]:
        """Passages of all parts, one per (reference, text start)."""
        seen: set[tuple[str | None, str | None, str]] = set()
        merged: list[PlatformPassage] = []
        for part in self.parts:
            for p in await part.search(actor, query, limit):
                key = (p.ref_kind, p.ref_id, " ".join(p.text.split())[:80])
                if key not in seen:
                    seen.add(key)
                    merged.append(p)
        return merged[: limit * len(self.parts)]
