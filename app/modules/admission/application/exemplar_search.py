"""Closest exemplars to a draft: TF-IDF cosine over the published library."""

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final
from uuid import UUID

from app.modules.admission.domain.exemplars import (
    Exemplar,
    ExemplarMatch,
    cosine,
    idf,
    kind_rank,
    rank_key,
    tfidf,
    tokens,
)
from app.modules.admission.ports.unit_of_work import UowFactory
from app.shared.clock import Clock

CORPUS_TTL_SECONDS: Final = 300


@dataclass(frozen=True, slots=True)
class _Corpus:
    """Published exemplars with their vectors, valid until `expires`."""

    items: tuple[Exemplar, ...]
    weights: dict[str, float]
    vectors: tuple[dict[str, float], ...]
    expires: float


class UowExemplarSource:
    """`ExemplarSource` over the repository, with the corpus cached for 300 s."""

    def __init__(
        self,
        uow: UowFactory,
        clock: Clock,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        """Keep the unit-of-work factory; `clock` is unused beyond wiring parity."""
        self._uow = uow
        self._clock = clock
        self._monotonic = monotonic
        self._corpus: _Corpus | None = None

    async def _load(self) -> _Corpus:
        now = self._monotonic()
        if self._corpus is not None and self._corpus.expires > now:
            return self._corpus
        async with self._uow() as uow:
            items = tuple(await uow.exemplars.published())
        docs = [tokens(f"{e.prompt} {e.body}") for e in items]
        weights = idf(docs)
        self._corpus = _Corpus(
            items,
            weights,
            tuple(tfidf(d, weights) for d in docs),
            now + CORPUS_TTL_SECONDS,
        )
        return self._corpus

    async def closest(
        self,
        *,
        kind: str,
        prompt: str,
        body: str,
        institution_id: UUID | None,
        k: int = 3,
    ) -> tuple[ExemplarMatch, ...]:
        """Published only, best first; an empty library gives `()`."""
        corpus = await self._load()
        if not corpus.items:
            return ()
        query = tfidf(tokens(f"{prompt} {body}"), corpus.weights)
        scored = [
            (rank_key(kind, institution_id, item, sim), ExemplarMatch(item, sim))
            for item, vec in zip(corpus.items, corpus.vectors, strict=True)
            if kind_rank(kind, item.kind) > 0
            for sim in (cosine(query, vec),)
        ]
        scored.sort(key=lambda p: p[0], reverse=True)
        return tuple(m for _, m in scored[: max(k, 0)])
