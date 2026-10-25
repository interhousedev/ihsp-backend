"""NB-14: the deterministic fake embeddings used in development and tests."""

import math

from app.modules.ai.infrastructure.fake_embeddings import (
    FakeEmbeddingGateway,
    fake_vector,
)
from app.shared.db.embeddings import EMBEDDING_DIMS

import pytest


def cosine(a: list[float], b: list[float]) -> float:
    """Cosine of two unit vectors."""
    return sum(x * y for x, y in zip(a, b, strict=True))


def test_the_same_text_always_gives_the_same_unit_vector() -> None:
    """Stable across calls (and processes: no `hash()` of str)."""
    first = fake_vector("Fotosintez jarayoni")
    second = fake_vector("Fotosintez jarayoni")

    assert first == second
    assert len(first) == EMBEDDING_DIMS
    assert math.isclose(math.sqrt(sum(v * v for v in first)), 1.0)


def test_texts_that_share_a_word_stem_are_closer_than_unrelated_texts() -> None:
    """'fotosintez' ~ 'fotosintezda'; both far from a text about taxes."""
    near = cosine(fake_vector("fotosintez"), fake_vector("fotosintezda"))
    far = cosine(fake_vector("fotosintez"), fake_vector("налоги и бюджет государства"))

    assert near > 0.5 > 0.2 > far


def test_an_empty_text_is_a_zero_vector() -> None:
    """No features, nothing to normalize."""
    assert set(fake_vector("   ")) == {0.0}


async def test_the_gateway_records_calls_and_counts_tokens() -> None:
    """Kind and texts are kept so tests can assert what was embedded."""
    gateway = FakeEmbeddingGateway()

    batch = await gateway.embed(["abcd", "abcdefgh"], kind="document")
    await gateway.embed(["q"], kind="query")

    assert len(batch.vectors) == 2
    assert batch.tokens == 2 + 3
    assert gateway.calls == [("document", ["abcd", "abcdefgh"]), ("query", ["q"])]
    assert gateway.texts == ["abcd", "abcdefgh", "q"]


async def test_the_gateway_can_be_told_to_fail() -> None:
    """Error injection for the job and query tests."""
    gateway = FakeEmbeddingGateway()
    gateway.error = RuntimeError("down")

    with pytest.raises(RuntimeError):
        await gateway.embed(["x"], kind="query")
