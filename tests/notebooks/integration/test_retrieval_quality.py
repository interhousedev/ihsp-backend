"""NB-14: words alone against words + meaning on a small trilingual question set.

The set is `fixtures/retrieval_eval.json`: 8 documents (Uzbek in Latin and in Cyrillic,
Russian, English), 64 passages and 64 questions, each with the passage(s) that answer
it and a `kind` that says why word matching alone may fail. The vectors are real
`qwen/qwen3-embedding-4b` vectors cached in `retrieval_eval_vectors.json` (refresh
them with `scripts/vector_eval.py`), so the test needs no network.

Run `pytest tests/notebooks/integration/test_retrieval_quality.py -s` to print the
table that docs/reference/vector-search.md quotes.
"""

import json
from collections import defaultdict
from pathlib import Path
from typing import Any
from uuid import UUID

from app.modules.notebooks.domain.entities import Notebook
from app.modules.notebooks.domain.passage_hash import passage_hash
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.modules.vectors.domain.packing import unpack
from app.modules.vectors.infrastructure.sql_embedding_store import SqlEmbeddingStore
from app.shared.actor import Actor
from app.shared.contracts.embeddings import QueryVector
from tests.factories.notebooks import make_notebook, make_source

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
KS = (1, 3, 5, 10, 24)  # 24 passages is what the chat reads
KINDS = (
    "keyword",
    "morphology",
    "typo",
    "paraphrase",
    "cross-script",
    "cross-language",
)
# A query without content words has an empty lexical ranking: the fused list is then
# the cosine ranking alone ("vector only").
NO_WORDS = "?"

Scores = dict[str, dict[int, float]]  # kind (or "all") -> k -> mean recall


def load() -> tuple[dict[str, Any], dict[str, Any]]:
    """The question set and its cached vectors."""
    data = json.loads((FIXTURES / "retrieval_eval.json").read_text(encoding="utf-8"))
    vectors = json.loads(
        (FIXTURES / "retrieval_eval_vectors.json").read_text(encoding="utf-8")
    )
    return data, vectors


@pytest.fixture
async def notebook(uow_factory: UowFactory, student: Actor) -> Notebook:
    """A notebook with one source per fixture document, vectors stored."""
    return await make_notebook(uow_factory, student.user_id)


async def prepare(
    uow_factory: UowFactory,
    notebook: Notebook,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> tuple[list[UUID], dict[str, str]]:
    """Store the documents and the passage vectors; returns source ids, text -> id."""
    data, vectors = load()
    store = SqlEmbeddingStore(sessionmaker)
    source_ids: list[UUID] = []
    ids_by_text: dict[str, str] = {}
    rows = []
    for document in data["documents"]:
        texts = tuple(p["text"] for p in document["passages"])
        source_ids.append((await make_source(uow_factory, notebook, texts=texts)).id)
        for passage in document["passages"]:
            ids_by_text[passage["text"]] = passage["id"]
            rows.append(
                (
                    passage_hash(passage["text"]),
                    unpack(vectors["passages"][passage["id"]]),
                )
            )
    await store.put(vectors["model"], rows)
    return source_ids, ids_by_text


async def evaluate(
    uow_factory: UowFactory,
    notebook: Notebook,
    source_ids: list[UUID],
    ids_by_text: dict[str, str],
    mode: str,
) -> Scores:
    """Mean recall@k for `words`, `vector` or `hybrid`, overall and per kind."""
    data, vectors = load()
    hits: dict[str, dict[int, list[float]]] = defaultdict(lambda: {k: [] for k in KS})
    for question in data["questions"]:
        query_vector = QueryVector(
            vectors["model"], unpack(vectors["questions"][question["id"]])
        )
        text = NO_WORDS if mode == "vector" else question["text"]
        async with uow_factory() as uow:
            found = await uow.passages.search(
                notebook.id,
                source_ids,
                text,
                max(KS),  # the chat's own limit, so the fusion is the production one
                query_vector=None if mode == "words" else query_vector,
            )
        ranked = [ids_by_text[p.text] for p in found]
        relevant = set(question["relevant"])
        for k in KS:
            recall = len(relevant & set(ranked[:k])) / len(relevant)
            hits["all"][k].append(recall)
            hits[question["kind"]][k].append(recall)
    return {
        kind: {k: sum(values) / len(values) for k, values in by_k.items()}
        for kind, by_k in hits.items()
    }


def table(results: dict[str, Scores]) -> str:
    """A text table of the three modes (recall@1, @3, @5 in percent)."""
    lines = ["kind            " + "".join(f"{m:^30}" for m in results)]
    lines.append("                " + "".join(f"  R@{k}" for k in KS) * len(results))
    for kind in ("all", *KINDS):
        row = f"{kind:16s}"
        for scores in results.values():
            row += "".join(f"{100 * scores[kind][k]:5.0f} " for k in KS) + "  "
        lines.append(row)
    return "\n".join(lines)


async def test_hybrid_search_beats_words_alone_on_the_trilingual_set(
    uow_factory: UowFactory,
    sessionmaker_in_tx: async_sessionmaker[AsyncSession],
    notebook: Notebook,
) -> None:
    """NB-14: the numbers behind docs/reference/vector-search.md."""
    source_ids, ids_by_text = await prepare(uow_factory, notebook, sessionmaker_in_tx)
    results = {
        mode: await evaluate(uow_factory, notebook, source_ids, ids_by_text, mode)
        for mode in ("words", "vector", "hybrid")
    }
    print("\n" + table(results))  # noqa: T201  (read with -s)

    words, vector, hybrid = results["words"], results["vector"], results["hybrid"]
    for k in KS:
        assert hybrid["all"][k] >= words["all"][k]
    assert hybrid["all"][5] >= 0.95
    assert hybrid["all"][1] - words["all"][1] >= 0.3  # the gain is large, not noise
    assert words["cross-script"][24] == 0  # the alphabets share no word
    assert hybrid["cross-script"][5] >= 0.95
    assert hybrid["cross-language"][5] >= 0.95
    assert vector["all"][5] >= 0.95
    # Words keep what they are good at: the exact questions are not made worse.
    for kind in ("keyword", "morphology"):
        assert hybrid[kind][3] >= words[kind][3]
