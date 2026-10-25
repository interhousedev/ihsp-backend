"""NB-14: `EmbedTexts` embeds each distinct text once, within the daily budget."""

from app.modules.ai.infrastructure.fake_embeddings import FakeEmbeddingGateway
from app.modules.vectors.application.embed_texts import EmbedTexts
from app.shared.contracts.embeddings import TextToEmbed
from tests.fakes.vectors.stores import FakeEmbeddingStore, FakeTokenBudget

import pytest


def item(n: int, text: str | None = None) -> TextToEmbed:
    """A text with a made-up 64 character hash."""
    return TextToEmbed(f"{n:064d}", text or f"text number {n}")


def build(
    *, batch_size: int = 32, limit: int | None = None
) -> tuple[EmbedTexts, FakeEmbeddingGateway, FakeEmbeddingStore, FakeTokenBudget]:
    """The use case over fakes."""
    gateway = FakeEmbeddingGateway(dims=8, batch_size=batch_size)
    store, budget = FakeEmbeddingStore(), FakeTokenBudget(limit)
    return (
        EmbedTexts(gateway=gateway, store=store, budget=budget),
        gateway,
        store,
        budget,
    )


async def test_every_distinct_text_is_embedded_and_stored_under_the_model() -> None:
    """The new texts reach the store keyed by hash and model."""
    use_case, gateway, store, _ = build()

    report = await use_case.execute([item(1), item(2)])

    assert report.embedded == 2 and report.already == 0 and report.deferred == 0
    assert set(store.rows) == {
        (gateway.model, item(1).content_hash),
        (gateway.model, item(2).content_hash),
    }
    assert gateway.calls[0][0] == "document"


async def test_the_same_hash_twice_in_one_call_is_embedded_once() -> None:
    """Two passages with one text (two documents) cost one vector."""
    use_case, gateway, _, _ = build()

    report = await use_case.execute([item(1, "same"), item(1, "same"), item(2)])

    assert report.embedded == 2
    assert gateway.texts == ["same", "text number 2"]


async def test_a_text_that_has_a_vector_is_not_sent_again() -> None:
    """Running the job twice pays once."""
    use_case, gateway, _, _ = build()
    await use_case.execute([item(1), item(2)])
    gateway.calls.clear()

    report = await use_case.execute([item(1), item(2), item(3)])

    assert report.embedded == 1 and report.already == 2
    assert gateway.texts == ["text number 3"]


async def test_texts_go_out_in_batches_of_the_configured_size() -> None:
    """Five texts, batch of two: three requests, one store write each."""
    use_case, gateway, store, _ = build(batch_size=2)

    await use_case.execute([item(n) for n in range(5)])

    assert [len(texts) for _, texts in gateway.calls] == [2, 2, 1]
    assert store.put_calls == [2, 2, 1]


async def test_blank_texts_are_skipped() -> None:
    """Providers reject empty input; there is nothing to find in it anyway."""
    use_case, gateway, _, _ = build()

    report = await use_case.execute([item(1, "   "), item(2)])

    assert report.embedded == 1
    assert gateway.texts == ["text number 2"]


async def test_the_daily_budget_stops_the_run_and_defers_the_rest() -> None:
    """Once the tokens are spent no further batch is sent."""
    use_case, gateway, store, budget = build(batch_size=2, limit=1)

    report = await use_case.execute([item(n) for n in range(6)])

    assert report.embedded == 2 and report.deferred == 4
    assert len(gateway.calls) == 1
    assert budget.spent == report.tokens > 0
    assert len(store.rows) == 2


async def test_without_a_limit_everything_is_embedded() -> None:
    """A limit of None never defers."""
    use_case, _, store, _ = build(batch_size=2, limit=None)

    report = await use_case.execute([item(n) for n in range(5)])

    assert report.deferred == 0 and len(store.rows) == 5


async def test_a_failure_keeps_what_the_earlier_batches_stored() -> None:
    """The first batch is stored before the second one fails."""
    use_case, gateway, store, _ = build(batch_size=2)
    calls = {"n": 0}
    original = gateway.embed

    async def flaky(texts: list[str], *, kind: str) -> object:
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("provider down")
        return await original(texts, kind="document")

    gateway.embed = flaky  # type: ignore[method-assign,assignment]

    with pytest.raises(RuntimeError):
        await use_case.execute([item(n) for n in range(4)])

    assert len(store.rows) == 2
