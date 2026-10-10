"""PlatformSearch over passages shared between notebooks (access-checked)."""

from app.modules.notebooks.application.shared_passage_search import (
    SharedPassage,
    SharedPassageSearch,
)
from app.shared.actor import Actor
from app.shared.contracts.web_search import PlatformPassage

PASSAGE_CHARS = 1200


class SharedPlatformSearch:
    """Hybrid search (vector + text, RRF) over what the actor may read."""

    def __init__(self, search: SharedPassageSearch) -> None:
        """Keep the use case."""
        self._search = search

    async def search(
        self, actor: Actor, query: str, limit: int
    ) -> list[PlatformPassage]:
        """Passages of the user's notebooks, public library items and own lessons."""
        found = await self._search.execute(actor, query, limit)
        return [_passage(p) for p in found]


def _passage(p: SharedPassage) -> PlatformPassage:
    text = p.text[:PASSAGE_CHARS]
    if p.origin == "library":
        return PlatformPassage(
            title=p.title,
            url=f"/library/{p.ref_id}",
            text=text,
            ref_kind="library_item",
            ref_id=str(p.ref_id),
        )
    if p.origin == "lesson":
        # Not the owner's notebook: point at the lesson, not at someone's notebook.
        return PlatformPassage(title=p.title, url=f"/lessons/{p.ref_id}", text=text)
    return PlatformPassage(
        title=p.title,
        url=f"/notebooks/{p.notebook_id}?source={p.source_id}",
        text=text,
        ref_kind="notebook_source",
        ref_id=str(p.source_id),
    )
