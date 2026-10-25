"""Give every distinct text a vector, once, within the daily token budget."""

from collections.abc import Sequence
from dataclasses import dataclass

from app.modules.vectors.ports.embedding_store import EmbeddingStore
from app.modules.vectors.ports.token_budget import TokenBudget
from app.shared.contracts.embeddings import (
    EmbeddingGateway,
    EmbedReport,
    TextToEmbed,
)

import structlog

log = structlog.get_logger(__name__)

MAX_TEXT_CHARS = 8_000  # a passage is at most 1 400; this only guards odd callers


@dataclass(slots=True)
class _Totals:
    embedded: int = 0
    tokens: int = 0
    cost_micro: int = 0


def _distinct(texts: Sequence[TextToEmbed]) -> list[TextToEmbed]:
    """The first text of every hash; blank texts have nothing to embed."""
    seen: dict[str, TextToEmbed] = {}
    for item in texts:
        if item.text.strip():
            seen.setdefault(item.content_hash, item)
    return list(seen.values())


class EmbedTexts:
    """`EmbeddingIndex.ensure`: the same text is embedded and paid for once.

    A text is known by the sha256 of its content, so two passages with the same text,
    in different documents, notebooks or modules, share one row. Texts are sent in
    batches; each batch is stored as soon as it arrives, so a failure later in the
    run loses nothing.
    """

    def __init__(
        self,
        *,
        gateway: EmbeddingGateway,
        store: EmbeddingStore,
        budget: TokenBudget,
    ) -> None:
        """Store the collaborators."""
        self.gateway = gateway
        self.store = store
        self.budget = budget

    async def execute(self, texts: Sequence[TextToEmbed]) -> EmbedReport:
        """Embed the texts that have no vector yet."""
        distinct = _distinct(texts)
        model = self.gateway.model
        have = await self.store.existing([t.content_hash for t in distinct], model)
        todo = [t for t in distinct if t.content_hash not in have]
        totals = _Totals()
        remaining = await self.budget.remaining()
        size = max(1, self.gateway.batch_size)
        deferred = 0
        for start in range(0, len(todo), size):
            if remaining is not None and remaining <= 0:
                deferred = len(todo) - start
                break
            spent = await self._embed_batch(todo[start : start + size], totals)
            remaining = None if remaining is None else remaining - spent
        report = EmbedReport(
            embedded=totals.embedded,
            already=len(distinct) - len(todo),
            deferred=deferred,
            tokens=totals.tokens,
            cost_micro=totals.cost_micro,
        )
        log.info(
            "vectors_embedded",
            model=model,
            embedded=report.embedded,
            already=report.already,
            deferred=report.deferred,
            tokens=report.tokens,
            cost_micro=report.cost_micro,
        )
        return report

    async def _embed_batch(self, batch: Sequence[TextToEmbed], totals: _Totals) -> int:
        """Embed and store one batch; returns the tokens it was billed."""
        result = await self.gateway.embed(
            [t.text[:MAX_TEXT_CHARS] for t in batch], kind="document"
        )
        await self.store.put(
            self.gateway.model,
            [(t.content_hash, v) for t, v in zip(batch, result.vectors, strict=True)],
        )
        await self.budget.spend(result.tokens)
        totals.embedded += len(batch)
        totals.tokens += result.tokens
        totals.cost_micro += result.cost_micro or 0
        return result.tokens
