"""Multi-hop retrieval: a small model names the gaps, retrieval fills them."""

from collections.abc import Awaitable, Callable, Sequence
from typing import Final

from app.modules.notebooks.application.llm import NotebookLlm
from app.modules.notebooks.domain.entities import Passage
from app.modules.notebooks.domain.retrieval_plan import (
    SUFFICIENCY_SCHEMA,
    SUFFICIENCY_SCHEMA_NAME,
    SUFFICIENCY_SYSTEM,
    clean_queries,
    new_passages,
    sufficiency_message,
)
from app.settings import Settings
from app.shared.ai_tasks import AiTask
from app.shared.contracts.ai import AiInvalidOutputError, AiProviderError

import structlog

log = structlog.get_logger(__name__)

# A search of the notebook: (query, limit) -> best passages first.
Search = Callable[[str, int], Awaitable[list[Passage]]]

FOLLOW_UP_HITS: Final = 8  # passages per follow-up query
PLAN_MAX_TOKENS: Final = 300  # a verdict and three short queries


class MultiHopRetrieval:
    """Asks a small model whether the hits answer the question; searches the gaps.

    Bounded by `NOTEBOOKS__MULTI_HOP_MAX_HOPS` cheap calls and
    `NOTEBOOKS__MULTI_HOP_QUERIES_PER_HOP` searches per call; it stops as soon as
    the model is satisfied or a round finds nothing new. Any model failure keeps
    the passages found so far.
    """

    def __init__(self, llm: NotebookLlm, settings: Settings) -> None:
        """Store the model and the settings."""
        self.llm = llm
        self.settings = settings

    @property
    def enabled(self) -> bool:
        """`NOTEBOOKS__MULTI_HOP_ENABLED` and at least one hop."""
        notebooks = self.settings.notebooks
        return notebooks.multi_hop_enabled and notebooks.multi_hop_max_hops > 0

    async def expand(
        self, question: str, hits: Sequence[Passage], search: Search
    ) -> list[Passage]:
        """The hits plus the new passages of the follow-up queries, deduplicated."""
        found = list(hits)
        if not self.enabled:
            return found
        asked: list[str] = [question]
        for _ in range(self.settings.notebooks.multi_hop_max_hops):
            queries = await self._follow_ups(question, found, asked)
            if not queries:
                break
            asked.extend(queries)
            fresh = await self._search_all(queries, found, search)
            if not fresh:
                break
            found.extend(fresh)
        return found

    async def _search_all(
        self, queries: Sequence[str], known: Sequence[Passage], search: Search
    ) -> list[Passage]:
        """The passages of the queries that are not known yet."""
        fresh: list[Passage] = []
        for query in queries:
            fresh.extend(
                new_passages([*known, *fresh], await search(query, FOLLOW_UP_HITS))
            )
        return fresh

    async def _follow_ups(
        self, question: str, found: Sequence[Passage], asked: Sequence[str]
    ) -> list[str]:
        """The model's queries for the gaps; none when it is satisfied or fails."""
        limit = self.settings.notebooks.multi_hop_queries_per_hop
        try:
            done = await self.llm.json(
                task=AiTask.RETRIEVAL_PLAN,
                system=SUFFICIENCY_SYSTEM,
                messages=[
                    {"role": "user", "content": sufficiency_message(question, found)}
                ],
                schema_name=SUFFICIENCY_SCHEMA_NAME,
                schema=SUFFICIENCY_SCHEMA,
                max_tokens=self.llm.max_tokens(AiTask.RETRIEVAL_PLAN, PLAN_MAX_TOKENS),
            )
        except (AiProviderError, AiInvalidOutputError) as exc:
            log.info("notebooks.multi_hop.skipped", error=type(exc).__name__)
            return []
        if done.data.get("sufficient") is True:
            return []
        return clean_queries(done.data.get("queries"), limit, seen=asked)
