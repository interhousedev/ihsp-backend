"""Use case: full-text search over the text of a notebook's sources (NB-14).

The lexical passage search of the assistant's `search_notebook` tool, grouped by
source for the Sources panel. Only usable sources are searched, selected or not.
"""

from dataclasses import dataclass
from uuid import UUID

from app.modules.notebooks.application.access import load_notebook
from app.modules.notebooks.domain.entities import Passage, Source
from app.modules.notebooks.domain.enums import SourceKind
from app.modules.notebooks.domain.errors import InvalidOptionsError
from app.modules.notebooks.domain.limits import (
    SEARCH_CANDIDATES_MAX,
    SEARCH_CANDIDATES_PER_HIT,
    SEARCH_HITS_PER_SOURCE,
    SEARCH_LIMIT_DEFAULT,
    SEARCH_LIMIT_MAX,
    SEARCH_QUERY_MAX_CHARS,
    SEARCH_QUERY_MIN_CHARS,
)
from app.modules.notebooks.domain.search_snippet import make_snippet
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.settings import Settings
from app.shared.actor import Actor
from app.shared.rate_limit import RateLimiter

RATE_WINDOW_SECONDS = 60


@dataclass(frozen=True, slots=True)
class SearchHit:
    """A passage that matches, with the text around the first match."""

    passage_id: UUID
    seq: int
    page: int | None
    snippet: str


@dataclass(frozen=True, slots=True)
class SourceHits:
    """The best passages of one source."""

    source_id: UUID
    title: str
    kind: SourceKind
    hits: list[SearchHit]


@dataclass(frozen=True, slots=True)
class SearchResult:
    """The request as it was searched and the sources with hits, best first."""

    query: str
    sources: list[SourceHits]


def clean_query(text: str) -> str:
    """The request as one line of 2 to 200 characters.

    Raises:
        InvalidOptionsError: The request is empty, too short or too long.
    """
    flat = " ".join(text.split())
    if not SEARCH_QUERY_MIN_CHARS <= len(flat) <= SEARCH_QUERY_MAX_CHARS:
        raise InvalidOptionsError(
            params={"reason": "text-length", "max": SEARCH_QUERY_MAX_CHARS}
        )
    return flat


class SearchSources:
    """Finds the passages of a notebook that contain the words of a request."""

    def __init__(
        self, *, uow_factory: UowFactory, settings: Settings, rate_limiter: RateLimiter
    ) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
        self.settings = settings
        self.rate_limiter = rate_limiter

    async def execute(
        self,
        actor: Actor,
        notebook_id: UUID,
        query: str,
        limit: int = SEARCH_LIMIT_DEFAULT,
    ) -> SearchResult:
        """Return up to `limit` hits (at most 3 per source) grouped by source.

        Sources come in the order of their best hit, hits within a source best
        first. A course member who may read the workspace may search it.

        Raises:
            InvalidOptionsError: The request is not 2 to 200 characters.
            NotebookNotFoundError: Not the caller's notebook.
            RateLimitedError: More than 30 searches in a minute.
        """
        clean = clean_query(query)
        size = max(1, min(limit, SEARCH_LIMIT_MAX))
        async with self.uow_factory() as uow:
            await load_notebook(uow, actor.user_id, notebook_id, write=False)
        await self.rate_limiter.hit(
            f"nb-search:{actor.user_id}",
            limit=self.settings.limits.nb_search_per_minute,
            window_seconds=RATE_WINDOW_SECONDS,
        )
        async with self.uow_factory() as uow:
            usable = [
                s for s in await uow.sources.list_for_notebook(notebook_id) if s.usable
            ]
            found = (
                await uow.passages.search(
                    notebook_id,
                    [s.id for s in usable],
                    clean,
                    min(size * SEARCH_CANDIDATES_PER_HIT, SEARCH_CANDIDATES_MAX),
                )
                if usable
                else []
            )
        return SearchResult(clean, _group(found, usable, clean, size))


def _group(
    found: list[Passage], usable: list[Source], query: str, size: int
) -> list[SourceHits]:
    """Group ranked passages by source: best first, 3 per source, `size` in all."""
    sources = {s.id: s for s in usable}
    groups: dict[UUID, list[SearchHit]] = {}
    total = 0
    for passage in found:
        hits = groups.setdefault(passage.source_id, [])
        if len(hits) < SEARCH_HITS_PER_SOURCE and total < size:
            hits.append(
                SearchHit(
                    passage_id=passage.id,
                    seq=passage.seq,
                    page=passage.page,
                    snippet=make_snippet(passage.text, query),
                )
            )
            total += 1
    return [
        SourceHits(sources[sid].id, sources[sid].title, sources[sid].kind, hits)
        for sid, hits in groups.items()
        if hits
    ]
