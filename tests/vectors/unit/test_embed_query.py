"""NB-14: `EmbedQuery` caches question vectors and never blocks a chat turn."""

import asyncio
from collections.abc import Sequence

from app.modules.ai.domain.errors import AiProviderError
from app.modules.ai.infrastructure.fake_embeddings import FakeEmbeddingGateway
from app.modules.vectors.application.embed_query import EmbedQuery, query_key
from app.shared.contracts.embeddings import EmbeddingBatch, EmbedKind
from tests.fakes.vectors.stores import FakeQueryCache, FakeTokenBudget


def build(
    gateway: FakeEmbeddingGateway | None = None, *, timeout: float = 1.0
) -> tuple[EmbedQuery, FakeEmbeddingGateway, FakeQueryCache, FakeTokenBudget]:
    """The use case over fakes."""
    gateway = gateway or FakeEmbeddingGateway(dims=8)
    cache, budget = FakeQueryCache(), FakeTokenBudget()
    use_case = EmbedQuery(
        gateway=gateway,
        cache=cache,
        budget=budget,
        timeout_seconds=timeout,
        cache_seconds=3600,
    )
    return use_case, gateway, cache, budget


async def test_a_question_is_embedded_as_a_query_and_cached() -> None:
    """The vector carries the model name; the cache keeps it for the configured time."""
    use_case, gateway, cache, budget = build()

    vector = await use_case.execute("What is photosynthesis?")

    assert vector is not None and vector.model == gateway.model
    assert len(vector.values) == 8
    assert gateway.calls == [("query", ["What is photosynthesis?"])]
    key = query_key(gateway.model, 8, "What is photosynthesis?")
    assert cache.values[key] == list(vector.values) and cache.ttl[key] == 3600
    assert budget.spent > 0


async def test_the_same_question_is_embedded_once() -> None:
    """Second and third turns with the same text cost nothing."""
    use_case, gateway, _, _ = build()

    first = await use_case.execute("What is photosynthesis?")
    second = await use_case.execute("What is   photosynthesis?\n")

    assert first == second
    assert len(gateway.calls) == 1


async def test_different_models_do_not_share_cache_entries() -> None:
    """The key names the model and the size."""
    assert query_key("a", 8, "q") != query_key("b", 8, "q")
    assert query_key("a", 8, "q") != query_key("a", 16, "q")


async def test_an_empty_question_has_no_vector() -> None:
    """Nothing to ask the provider."""
    use_case, gateway, _, _ = build()

    assert await use_case.execute("  \n ") is None
    assert gateway.calls == []


async def test_a_provider_error_means_no_vector_and_nothing_cached() -> None:
    """The caller falls back to words."""
    use_case, gateway, cache, _ = build()
    gateway.error = AiProviderError(support_details="down")

    assert await use_case.execute("question") is None
    assert cache.values == {}


class SlowGateway(FakeEmbeddingGateway):
    """A gateway that takes longer than the deadline."""

    async def embed(self, texts: Sequence[str], *, kind: EmbedKind) -> EmbeddingBatch:
        """Sleep, then answer."""
        await asyncio.sleep(1)
        return await super().embed(texts, kind=kind)


async def test_a_slow_provider_is_given_up_on_at_the_deadline() -> None:
    """A chat turn waits at most the configured seconds."""
    use_case, _, cache, _ = build(SlowGateway(dims=8), timeout=0.05)

    assert await use_case.execute("question") is None
    assert cache.values == {}


async def test_a_very_long_query_is_cut() -> None:
    """Only the first 2 000 characters are embedded."""
    use_case, gateway, _, _ = build()

    await use_case.execute("word " * 1000)

    assert len(gateway.calls[0][1][0]) == 2000
