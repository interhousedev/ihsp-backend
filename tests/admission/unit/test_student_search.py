"""Hybrid search over one student's data: ranking, isolation, forget, reindex."""

from datetime import timedelta
from uuid import UUID

from app.modules.admission.application.student_search import StudentSearchService
from app.modules.admission.domain.student_chunks import (
    Chunk,
    fuse,
    make_chunks,
    url_path,
)
from tests.admission.unit.fakes import NOW
from tests.fakes.admission_chunk_store import FakeChunkCollector, InMemoryChunkStore
from tests.fakes.ai.web_pages import FakeEmbeddingIndex
from tests.fakes.clock import FixedClock

A = UUID("00000000-0000-0000-0000-00000000000a")
B = UUID("00000000-0000-0000-0000-00000000000b")


class _Rig:
    def __init__(self, *, embeddings: bool = True) -> None:
        self.vectors: dict[str, list[float]] = {}
        self.store = InMemoryChunkStore(self.vectors)
        self.collector = FakeChunkCollector()
        self.index = FakeEmbeddingIndex(self.vectors)
        self.clock = FixedClock(NOW)
        self.service = StudentSearchService(
            self.store,
            self.collector,
            lambda: self.index if embeddings else None,
            self.clock,
        )


def _chunks() -> list[Chunk]:
    return [
        *make_chunks("item", "i1", "Robotics club", "Led a robotics team of ten"),
        *make_chunks("essay", "e1", "Why CS", "I love building compilers " * 3),
        *make_chunks("task", "t1", "Visa", "Book the embassy appointment"),
    ]


async def test_search_ranks_the_matching_row_first_with_url() -> None:
    r = _Rig()
    r.collector.put(A, _chunks(), NOW)
    hits = await r.service.search(A, "robotics team")
    assert hits[0].source == "item" and hits[0].ref_id == "i1"
    assert hits[0].url_path == "/activities"
    assert hits[0].score > 0 and "robotics" in hits[0].snippet.lower()
    essay = await r.service.search(A, "compilers", sources=("essay",))
    assert [h.url_path for h in essay] == ["/essays/e1"]


async def test_sources_filter_and_blank_query() -> None:
    r = _Rig()
    r.collector.put(A, _chunks(), NOW)
    assert await r.service.search(A, "   ") == []
    assert all(
        h.source == "task" for h in await r.service.search(A, "visa", sources=("task",))
    )
    far = await r.service.search(A, "robotics", sources=("task",))
    assert all(h.source == "task" for h in far)


async def test_students_are_isolated() -> None:
    r = _Rig()
    r.collector.put(A, _chunks(), NOW)
    r.collector.put(B, make_chunks("item", "b1", "Chess", "Chess champion"), NOW)
    assert [h.ref_id for h in await r.service.search(B, "robotics")] != ["i1"]
    assert all(h.ref_id == "b1" for h in await r.service.search(B, "robotics chess"))
    assert all(h.ref_id != "b1" for h in await r.service.search(A, "robotics chess"))


async def test_forget_drops_only_that_student() -> None:
    r = _Rig()
    r.collector.put(A, _chunks(), NOW)
    r.collector.put(B, make_chunks("item", "b1", "Chess", "Chess champion"), NOW)
    await r.service.reindex(A)
    await r.service.reindex(B)
    await r.service.forget(A)
    assert A not in r.store.chunks and B in r.store.chunks
    assert await r.store.indexed_at(A) is None


async def test_forget_drops_unshared_vectors_only() -> None:
    r = _Rig()
    shared = make_chunks("item", "s", "Shared", "Same text for both")
    r.collector.put(A, [*shared, *make_chunks("item", "a", "Mine", "Only A text")], NOW)
    r.collector.put(B, shared, NOW)
    await r.service.reindex(A)
    await r.service.reindex(B)
    only_a = {c.content_hash for c in r.store.chunks[A]} - {
        c.content_hash for c in r.store.chunks[B]
    }
    assert only_a and only_a <= r.vectors.keys()
    await r.service.forget(A)
    assert not only_a & r.vectors.keys()
    assert {c.content_hash for c in r.store.chunks[B]} <= r.vectors.keys()


async def test_reindex_counts_and_embeds() -> None:
    r = _Rig()
    r.collector.put(A, _chunks(), NOW)
    assert await r.service.reindex(A) == 3
    assert len(r.index.ensured) == 3 and len(r.vectors) == 3
    r.collector.put(A, _chunks()[:1], NOW)
    assert await r.service.reindex(A) == 1
    assert len(r.store.chunks[A]) == 1


async def test_lazy_reindex_only_when_data_is_newer() -> None:
    r = _Rig()
    r.collector.put(A, _chunks(), NOW)
    await r.service.search(A, "visa")
    await r.service.search(A, "visa")
    assert r.collector.collects == 1
    r.collector.put(A, _chunks(), NOW + timedelta(hours=1))
    r.clock.advance(hours=2)
    await r.service.search(A, "visa")
    assert r.collector.collects == 2


async def test_no_data_means_no_index_and_no_hits() -> None:
    r = _Rig()
    assert await r.service.search(A, "anything") == []
    assert r.collector.collects == 0


async def test_words_only_without_embeddings() -> None:
    r = _Rig(embeddings=False)
    r.collector.put(A, _chunks(), NOW)
    hits = await r.service.search(A, "embassy")
    assert [h.ref_id for h in hits] == ["t1"]
    assert r.vectors == {}


def test_long_essay_is_split_and_hits_collapse_per_row() -> None:
    chunks = make_chunks("essay", "e9", "T", "word " * 1000)
    assert 1 < len(chunks) <= 6 and [c.seq for c in chunks] == list(range(len(chunks)))
    ranked = fuse([[("essay", "e9"), ("essay", "e9"), ("item", "x")]])
    assert [k for k, _ in ranked] == [("essay", "e9"), ("item", "x")]


def test_url_paths() -> None:
    assert url_path("essay", "abc") == "/essays/abc"
    assert url_path("grade", "g") == url_path("course", "g") == "/courses"


async def test_deleted_row_triggers_rebuild() -> None:
    r = _Rig()
    r.collector.put(A, _chunks(), NOW)
    await r.service.search(A, "visa")
    r.collector.put(A, _chunks()[:2], NOW)  # same stamp, one row fewer
    assert [
        h.ref_id for h in await r.service.search(A, "embassy", sources=("task",))
    ] == []
    r.collector.put(A, [], NOW)
    r.collector.changed.pop(A)
    assert await r.service.search(A, "robotics") == []
    assert A in r.store.chunks and r.store.chunks[A] == []


async def test_unrelated_vector_hits_are_cut_off() -> None:
    r = _Rig()
    r.collector.put(A, make_chunks("item", "z", "Zzzz", "qqqq xxxx"), NOW)
    assert await r.service.search(A, "chemistry olympiad medal") == []


def test_task_and_test_paths() -> None:
    assert url_path("task", "t") == "/tasks" and url_path("test_score", "s") == "/tests"
