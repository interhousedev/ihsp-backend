"""NB-14: hybrid passage search (words + meaning) and the texts that lack a vector."""

from uuid import UUID

from app.modules.notebooks.domain.entities import Notebook, Passage
from app.modules.notebooks.domain.passage_hash import passage_hash
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.modules.vectors.infrastructure.sql_embedding_store import SqlEmbeddingStore
from app.shared.actor import Actor
from app.shared.contracts.embeddings import QueryVector
from app.shared.db.embeddings import EMBEDDING_DIMS
from tests.factories.notebooks import make_notebook, make_source

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

MODEL = "test/model"

SUGAR = "Plants make sugar from light in the leaves."
CAT = "The cat sat on the warm windowsill all afternoon."
TAXES = "Governments collect taxes to pay for schools."


def unit(index: int, *, other: int | None = None) -> list[float]:
    """A vector with a 1 at `index` (and at `other`), zeros elsewhere."""
    values = [0.0] * EMBEDDING_DIMS
    values[index] = 1.0
    if other is not None:
        values[other] = 1.0
    return values


@pytest.fixture
def store(sessionmaker_in_tx: async_sessionmaker[AsyncSession]) -> SqlEmbeddingStore:
    """The vectors table over the test transaction."""
    return SqlEmbeddingStore(sessionmaker_in_tx)


@pytest.fixture
async def notebook(uow_factory: UowFactory, student: Actor) -> Notebook:
    """A stored notebook."""
    return await make_notebook(uow_factory, student.user_id)


async def search(
    uow_factory: UowFactory,
    notebook: Notebook,
    source_ids: list[UUID],
    query: str,
    *,
    vector: list[float] | None = None,
    model: str = MODEL,
    limit: int = 10,
) -> list[str]:
    """The texts found, best first."""
    async with uow_factory() as uow:
        found = await uow.passages.search(
            notebook.id,
            source_ids,
            query,
            limit,
            query_vector=None if vector is None else QueryVector(model, vector),
        )
    return [p.text for p in found]


async def test_without_a_vector_the_search_is_the_lexical_one(
    uow_factory: UowFactory, notebook: Notebook, store: SqlEmbeddingStore
) -> None:
    """NB-14: no query vector, no change: only passages with a matching word."""
    source = await make_source(uow_factory, notebook, texts=(SUGAR, CAT, TAXES))
    await store.put(MODEL, [(passage_hash(CAT), unit(3))])

    found = await search(uow_factory, notebook, [source.id], "sugar")

    assert found == [SUGAR]


async def test_a_passage_without_the_query_words_is_found_by_its_vector(
    uow_factory: UowFactory, notebook: Notebook, store: SqlEmbeddingStore
) -> None:
    """NB-14: another language or a paraphrase: no shared word, near vector."""
    source = await make_source(uow_factory, notebook, texts=(SUGAR, CAT, TAXES))
    await store.put(
        MODEL, [(passage_hash(CAT), unit(3)), (passage_hash(TAXES), unit(9))]
    )

    found = await search(
        uow_factory, notebook, [source.id], "sugar", vector=unit(3, other=9)
    )

    # 1st by meaning and 1st by words tie; meaning wins ties; then 2nd by meaning.
    assert found == [CAT, SUGAR, TAXES]


async def test_a_passage_that_both_rankings_like_comes_first(
    uow_factory: UowFactory, notebook: Notebook, store: SqlEmbeddingStore
) -> None:
    """NB-14: reciprocal rank fusion rewards agreement."""
    both = "Sugar is made by plants; light is the energy source."
    only_words = "Sugar sugar sugar in a bowl, sugar everywhere."
    only_meaning = "Glucose forms in leaves."
    source = await make_source(
        uow_factory, notebook, texts=(only_words, both, only_meaning)
    )
    await store.put(
        MODEL,
        [
            (passage_hash(only_words), unit(5)),
            (passage_hash(both), unit(0, other=1)),
            (passage_hash(only_meaning), unit(0)),
        ],
    )
    query = unit(0, other=1)  # nearest: both, then only_meaning, then only_words

    found = await search(uow_factory, notebook, [source.id], "sugar", vector=query)

    assert found[0] == both
    assert set(found) == {only_words, both, only_meaning}


async def test_when_no_passage_has_a_vector_the_result_is_the_lexical_one(
    uow_factory: UowFactory, notebook: Notebook
) -> None:
    """NB-14: embeddings missing (job not run, feature just switched on)."""
    source = await make_source(uow_factory, notebook, texts=(SUGAR, CAT, TAXES))

    lexical = await search(uow_factory, notebook, [source.id], "sugar light")
    hybrid = await search(
        uow_factory, notebook, [source.id], "sugar light", vector=unit(3)
    )

    assert hybrid == lexical == [SUGAR]


async def test_vectors_of_another_model_are_not_compared(
    uow_factory: UowFactory, notebook: Notebook, store: SqlEmbeddingStore
) -> None:
    """NB-14: vectors of two models live in two spaces; the query's model counts."""
    source = await make_source(uow_factory, notebook, texts=(SUGAR, CAT))
    await store.put("other/model", [(passage_hash(CAT), unit(3))])

    found = await search(uow_factory, notebook, [source.id], "sugar", vector=unit(3))

    assert found == [SUGAR]


async def test_a_vector_of_the_wrong_size_is_ignored(
    uow_factory: UowFactory, notebook: Notebook, store: SqlEmbeddingStore
) -> None:
    """NB-14: a query vector that does not fit the column falls back to words."""
    source = await make_source(uow_factory, notebook, texts=(SUGAR, CAT))
    await store.put(MODEL, [(passage_hash(CAT), unit(3))])

    found = await search(
        uow_factory, notebook, [source.id], "sugar", vector=[1.0, 0.0, 0.0]
    )

    assert found == [SUGAR]


async def test_only_the_selected_sources_of_the_notebook_are_searched(
    uow_factory: UowFactory,
    notebook: Notebook,
    other_student: Actor,
    store: SqlEmbeddingStore,
) -> None:
    """NB-14, NB-17: not a deselected source, not another student's notebook."""
    chosen = await make_source(uow_factory, notebook, texts=(SUGAR,))
    unchosen = await make_source(uow_factory, notebook, texts=(CAT,))
    theirs = await make_notebook(uow_factory, other_student.user_id)
    await make_source(uow_factory, theirs, texts=(TAXES,))
    await store.put(
        MODEL,
        [(passage_hash(t), unit(3)) for t in (SUGAR, CAT, TAXES)],
    )

    found = await search(uow_factory, notebook, [chosen.id], "x", vector=unit(3))
    both = await search(
        uow_factory, notebook, [chosen.id, unchosen.id], "x", vector=unit(3)
    )

    assert found == [SUGAR]
    assert set(both) == {SUGAR, CAT}


async def test_the_limit_applies_to_the_fused_list(
    uow_factory: UowFactory, notebook: Notebook, store: SqlEmbeddingStore
) -> None:
    """NB-14: a hybrid search returns at most `limit` passages."""
    texts = tuple(f"Sugar fact number {n}." for n in range(8))
    source = await make_source(uow_factory, notebook, texts=texts)
    await store.put(MODEL, [(passage_hash(t), unit(n)) for n, t in enumerate(texts)])

    found = await search(
        uow_factory, notebook, [source.id], "sugar", vector=unit(2), limit=3
    )

    # words: 0,1,2,...  meaning: 2,0,1,...  ->  fused 1/61+1/62 > 1/61+1/63 > 1/62+1/63
    assert found == [texts[0], texts[2], texts[1]]


async def test_a_text_held_by_two_sources_is_returned_for_each_source(
    uow_factory: UowFactory, notebook: Notebook, store: SqlEmbeddingStore
) -> None:
    """NB-5: the notebook thinks in sources; so does the fused list."""
    first = await make_source(uow_factory, notebook, texts=(SUGAR,))
    second = await make_source(uow_factory, notebook, texts=(SUGAR, CAT))
    await store.put(MODEL, [(passage_hash(CAT), unit(3))])
    async with uow_factory() as uow:
        found: list[Passage] = await uow.passages.search(
            notebook.id,
            [first.id, second.id],
            "sugar",
            10,
            query_vector=QueryVector(MODEL, unit(3)),
        )

    assert sorted((p.source_id, p.text) for p in found) == sorted(
        [(first.id, SUGAR), (second.id, SUGAR), (second.id, CAT)]
    )


# - - - passages that still need a vector - - -


async def test_missing_embeddings_lists_each_distinct_text_once(
    uow_factory: UowFactory, notebook: Notebook, store: SqlEmbeddingStore
) -> None:
    """NB-14: two documents with one shared passage text: one entry for it."""
    await make_source(uow_factory, notebook, texts=(SUGAR, CAT))
    await make_source(uow_factory, notebook, texts=(CAT, TAXES))

    async with uow_factory() as uow:
        missing = await uow.passages.missing_embeddings(MODEL, 100)

    assert sorted(m.text for m in missing) == sorted([SUGAR, CAT, TAXES])
    assert {m.content_hash for m in missing} == {
        passage_hash(t) for t in (SUGAR, CAT, TAXES)
    }


async def test_missing_embeddings_skips_texts_that_have_a_vector_of_the_model(
    uow_factory: UowFactory, notebook: Notebook, store: SqlEmbeddingStore
) -> None:
    """NB-14: a text with a vector of another model is still missing for this one."""
    await make_source(uow_factory, notebook, texts=(SUGAR, CAT))
    await store.put(MODEL, [(passage_hash(SUGAR), unit(1))])
    await store.put("other/model", [(passage_hash(CAT), unit(1))])

    async with uow_factory() as uow:
        missing = await uow.passages.missing_embeddings(MODEL, 100)

    assert [m.text for m in missing] == [CAT]


async def test_missing_embeddings_can_be_limited_to_a_document_and_a_count(
    uow_factory: UowFactory, notebook: Notebook
) -> None:
    """NB-14: the per-document kick and the capped backfill."""
    first = await make_source(uow_factory, notebook, texts=(SUGAR, CAT))
    await make_source(uow_factory, notebook, texts=(TAXES,))
    assert first.document_id is not None

    async with uow_factory() as uow:
        of_document = await uow.passages.missing_embeddings(
            MODEL, 100, document_id=first.document_id
        )
        capped = await uow.passages.missing_embeddings(MODEL, 2)

    assert sorted(m.text for m in of_document) == sorted([SUGAR, CAT])
    assert len(capped) == 2
