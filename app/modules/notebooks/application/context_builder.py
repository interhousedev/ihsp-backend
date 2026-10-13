"""Builds the context pack of a chat question or a Studio output (§ 3.3.2)."""

from collections import defaultdict
from collections.abc import Sequence
from functools import partial
from uuid import UUID

from app.modules.notebooks.application.retrieval_expander import RetrievalExpander
from app.modules.notebooks.domain.context import ContextPack
from app.modules.notebooks.domain.context_policy import (
    allocate_tokens,
    build_pack,
    choose_chat_mode,
    choose_studio_mode,
    evenly_spaced,
    expand_with_neighbours,
    retrieval_query,
)
from app.modules.notebooks.domain.entities import (
    AnchorPassages,
    AnchorText,
    Passage,
    Source,
)
from app.modules.notebooks.ports.unit_of_work import NotebooksUnitOfWork
from app.settings import Settings
from app.shared.contracts.embeddings import EmbeddingIndex, QueryVector
from app.shared.features import Feature, is_enabled

RETRIEVAL_HITS = 24
RETRIEVAL_MAX_PASSAGES = 40
FALLBACK_PASSAGES_PER_SOURCE = 3  # when a question matches nothing
PROMPT_HITS = 24  # passages added to a Studio sample for the student's focus
FOCUS_SHARE = 10  # 1/10 of the Studio cap is kept for the focus passages


def _group(passages: Sequence[Passage]) -> dict[UUID, list[Passage]]:
    grouped: dict[UUID, list[Passage]] = defaultdict(list)
    for passage in passages:
        grouped[passage.source_id].append(passage)
    return grouped


def _add_within(
    chosen: dict[UUID, list[Passage]], hits: Sequence[Passage], room: int
) -> None:
    """Add the focus passages that are not chosen yet, best first, within `room`."""
    for hit in hits:
        picked = chosen.setdefault(hit.source_id, [])
        if hit.token_estimate <= room and all(hit.id != p.id for p in picked):
            picked.append(hit)
            room -= hit.token_estimate


class ContextBuilder:
    """Chooses the passages a model call sees: all, the best matches, or a sample.

    The methods take an open unit of work and the selected, usable sources ordered
    by position; source ``n`` of the labels is the index in that list (in retrieval
    mode only the sources that contribute passages are kept, so the labels are
    numbered over them).
    """

    def __init__(
        self,
        settings: Settings,
        embeddings: EmbeddingIndex | None = None,
        expander: RetrievalExpander | None = None,
    ) -> None:
        """Store the caps (`chat_full_context_tokens`, `studio_context_tokens`).

        With `embeddings` (and `FEATURES__VECTOR_SEARCH` on) retrieval is hybrid:
        words and meaning. Without them it is the lexical search of old.
        `expander` adds query decomposition and multi-hop retrieval to the chat.
        """
        self.settings = settings
        self.embeddings = embeddings
        self.expander = expander

    async def _query_vector(self, query: str) -> QueryVector | None:
        """The vector of a retrieval query; None when meaning search is off or slow."""
        if self.embeddings is None or not is_enabled(
            self.settings, Feature.VECTOR_SEARCH
        ):
            return None
        return await self.embeddings.embed_query(query)

    # - - - Chat - - -

    async def for_chat(
        self,
        uow: NotebooksUnitOfWork,
        notebook_id: UUID,
        sources: Sequence[Source],
        *,
        question: str,
        previous_user_text: str | None,
        anchor: AnchorPassages | AnchorText | None,
    ) -> ContextPack:
        """Full context up to the cap, else the best matches with neighbours."""
        ids = [s.id for s in sources]
        if not ids:  # no sources picked: nothing to read or search
            return build_pack([], {}, "full")
        total = sum(s.token_estimate for s in sources)
        cap = self.settings.notebooks.chat_full_context_tokens
        if choose_chat_mode(total, cap) == "full":
            passages = await uow.passages.list_for_sources(ids)
            return build_pack(sources, _group(passages), "full")
        pinned = await self._pinned(uow, notebook_id, set(ids), anchor)
        query = retrieval_query(question, previous_user_text)
        search = partial(self._search, uow, notebook_id, ids)
        if self.expander is None:
            hits = await search(query, RETRIEVAL_HITS)
        else:
            hits = await self.expander.hits(query, search, RETRIEVAL_HITS)
        if not hits and not pinned:
            return await self._fallback(uow, sources)
        by_source = await self._neighbour_index(uow, sources, [*hits, *pinned])
        chosen = expand_with_neighbours(
            by_source,
            hits,
            max_passages=RETRIEVAL_MAX_PASSAGES,
            pinned=pinned,
        )
        grouped = _group(chosen)
        contributing = [s for s in sources if s.id in grouped]
        return build_pack(contributing, grouped, "retrieval", guides=True)

    async def _search(
        self,
        uow: NotebooksUnitOfWork,
        notebook_id: UUID,
        source_ids: Sequence[UUID],
        query: str,
        limit: int,
    ) -> list[Passage]:
        """The best passages for a query: by words and, when available, by meaning."""
        vector = await self._query_vector(query)
        if vector is None:
            return await uow.passages.search(notebook_id, source_ids, query, limit)
        return await uow.passages.search(
            notebook_id, source_ids, query, limit, query_vector=vector
        )

    async def _pinned(
        self,
        uow: NotebooksUnitOfWork,
        notebook_id: UUID,
        source_ids: set[UUID],
        anchor: AnchorPassages | AnchorText | None,
    ) -> list[Passage]:
        """Anchored passages that belong to the selected sources."""
        if not isinstance(anchor, AnchorPassages) or not anchor.ids:
            return []
        found = await uow.passages.get_many(anchor.ids, notebook_id)
        return sorted(
            (p for p in found if p.source_id in source_ids),
            key=lambda p: (p.source_id, p.seq),
        )

    async def _neighbour_index(
        self,
        uow: NotebooksUnitOfWork,
        sources: Sequence[Source],
        seeds: Sequence[Passage],
    ) -> dict[UUID, list[Passage]]:
        """The seeds and their direct neighbours, keyed by source in source order."""
        found: dict[UUID, dict[int, Passage]] = {s.id: {} for s in sources}
        for seed in seeds:
            found[seed.source_id][seed.seq] = seed
            before, after = await uow.passages.neighbours(seed.source_id, seed.seq, 1)
            for passage in (*before, *after):
                found[passage.source_id][passage.seq] = passage
        return {
            sid: [p for _, p in sorted(by_seq.items())] for sid, by_seq in found.items()
        }

    async def _fallback(
        self, uow: NotebooksUnitOfWork, sources: Sequence[Source]
    ) -> ContextPack:
        """A question that matches nothing still gets the opening of every source."""
        chosen: dict[UUID, list[Passage]] = {}
        for source in sources:
            chosen[source.id] = await uow.passages.list_for_source(
                source.id, after_seq=0, limit=FALLBACK_PASSAGES_PER_SOURCE
            )
        return build_pack(sources, chosen, "retrieval", guides=True)

    # - - - Studio - - -

    async def for_studio(
        self,
        uow: NotebooksUnitOfWork,
        notebook_id: UUID,
        sources: Sequence[Source],
        *,
        prompt: str | None,
        cap_tokens: int,
    ) -> ContextPack:
        """Everything up to `cap_tokens`, else an even sample plus focus matches."""
        ids = [s.id for s in sources]
        total = sum(s.token_estimate for s in sources)
        passages = await uow.passages.list_for_sources(ids)
        by_source = _group(passages)
        if choose_studio_mode(total, cap_tokens) == "full":
            return build_pack(sources, by_source, "full")
        reserve = cap_tokens // FOCUS_SHARE if prompt else 0
        sizes = {s.id: s.token_estimate for s in sources}
        budgets = allocate_tokens(sizes, cap_tokens - reserve)
        chosen: dict[UUID, list[Passage]] = {
            sid: evenly_spaced(by_source.get(sid, ()), budgets[sid]) for sid in ids
        }
        if prompt:
            used = sum(p.token_estimate for picked in chosen.values() for p in picked)
            hits = await self._search(uow, notebook_id, ids, prompt, PROMPT_HITS)
            _add_within(chosen, hits, cap_tokens - used)
        for sid in ids:
            chosen[sid].sort(key=lambda p: p.seq)
        return build_pack(sources, chosen, "sample")
