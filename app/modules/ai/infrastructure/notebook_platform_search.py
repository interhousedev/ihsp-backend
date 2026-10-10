"""Platform search over the notebooks the user can read (via NotebooksQueries)."""

from uuid import UUID

from app.modules.ai.application.late_bindings import LateBindings
from app.shared.actor import Actor
from app.shared.contracts.web_search import PlatformPassage

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
                    )
                )
        return found[:limit]
