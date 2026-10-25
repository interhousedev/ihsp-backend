"""Shared passage search: ranking comes from the reader, access from the use case."""

from typing import Any
from uuid import UUID, uuid4

from app.modules.notebooks.application.shared_passage_search import (
    SharedPassageSearch,
)
from app.modules.notebooks.ports.shared_passages import SharedCandidate
from app.shared.actor import Actor, Role
from app.shared.contracts.embeddings import QueryVector
from tests.factories import make_actor as build_actor

ME = uuid4()
OTHER = uuid4()
OPEN_ITEM = uuid4()
HIDDEN_ITEM = uuid4()
MY_LESSON = uuid4()
OTHER_LESSON = uuid4()


def actor() -> Actor:
    """A student."""
    return build_actor(Role.STUDENT, user_id=ME)


def cand(
    text: str,
    *,
    owner: UUID = OTHER,
    kind: str = "file",
    ref: dict[str, Any] | None = None,
    passage: UUID | None = None,
) -> SharedCandidate:
    """A candidate row."""
    return SharedCandidate(
        passage_id=passage or uuid4(),
        source_id=uuid4(),
        notebook_id=uuid4(),
        owner_id=owner,
        kind=kind,
        ref=ref or {},
        source_title="T",
        text=text,
    )


class FakeReader:
    """Returns fixed candidates and records the call."""

    def __init__(self, rows: list[SharedCandidate]) -> None:
        self.rows = rows
        self.calls: list[tuple[UUID, str, QueryVector | None, int]] = []

    async def search(
        self, user_id: UUID, query: str, query_vector: QueryVector | None, limit: int
    ) -> list[SharedCandidate]:
        self.calls.append((user_id, query, query_vector, limit))
        return self.rows


class FakeLibrary:
    """Lets the user describe OPEN_ITEM only."""

    async def describe(self, item_id: UUID, actor: Actor) -> object:
        if item_id != OPEN_ITEM:
            raise PermissionError(str(item_id))
        return object()


class FakeSchedule:
    """The user attends MY_LESSON only."""

    async def is_in_audience(self, user_id: UUID, lesson_id: UUID) -> bool:
        return user_id == ME and lesson_id == MY_LESSON


class FakeEmbeddings:
    """A constant query vector."""

    async def embed_query(self, text: str) -> QueryVector | None:
        return QueryVector("m", [1.0])


def make(rows: list[SharedCandidate], *, embeddings: bool = True) -> tuple[Any, Any]:
    """The use case over fakes and its reader."""
    reader = FakeReader(rows)
    search = SharedPassageSearch(
        reader=reader,  # type: ignore[arg-type]
        library=FakeLibrary(),  # type: ignore[arg-type]
        schedule=FakeSchedule(),  # type: ignore[arg-type]
        embeddings=FakeEmbeddings() if embeddings else None,  # type: ignore[arg-type]
    )
    return search, reader


async def test_foreign_private_passages_are_dropped() -> None:
    """Another student's notebook source never comes back; the user's own does."""
    rows = [
        cand("theirs"),
        cand("mine", owner=ME),
        cand("their library", kind="library_item", ref={"item_id": str(HIDDEN_ITEM)}),
        cand(
            "their lesson", kind="lesson_resource", ref={"lesson_id": str(OTHER_LESSON)}
        ),
    ]
    search, _ = make(rows)

    found = await search.execute(actor(), "q", 5)

    assert [p.text for p in found] == ["mine"]


async def test_library_and_lesson_sources_need_access() -> None:
    """Readable library items and attended lessons come back with their own ids."""
    rows = [
        cand("book", kind="library_item", ref={"item_id": str(OPEN_ITEM)}),
        cand("lesson", kind="lesson_resource", ref={"lesson_id": str(MY_LESSON)}),
    ]
    search, _ = make(rows)

    found = await search.execute(actor(), "q", 5)

    assert [(p.origin, p.ref_id) for p in found] == [
        ("library", OPEN_ITEM),
        ("lesson", MY_LESSON),
    ]


async def test_bad_refs_and_failing_checks_fail_closed() -> None:
    """A malformed ref, or a missing collaborator, never lets a passage through."""
    rows = [
        cand("x", kind="library_item", ref={"item_id": "not-a-uuid"}),
        cand("y", kind="lesson_resource", ref={}),
    ]
    search, _ = make(rows)
    assert await search.execute(actor(), "q", 5) == []

    closed = SharedPassageSearch(
        reader=FakeReader(  # type: ignore[arg-type]
            [cand("b", kind="library_item", ref={"item_id": str(OPEN_ITEM)})]
        ),
        library=None,
        schedule=None,
        embeddings=None,
    )
    assert await closed.execute(actor(), "q", 5) == []


async def test_same_passage_through_two_sources_counts_once() -> None:
    """A text held by several sources is one hit; the accessible source is used."""
    shared = uuid4()
    rows = [
        cand("t", passage=shared),
        cand("t", passage=shared, owner=ME),
        cand("t", passage=shared, owner=ME),
    ]
    search, _ = make(rows)

    found = await search.execute(actor(), "q", 5)

    assert len(found) == 1 and found[0].origin == "notebook"


async def test_limit_query_and_vector_reach_the_reader() -> None:
    """The query is flattened, embedded and over-fetched; the result is cut."""
    rows = [cand(f"p{i}", owner=ME) for i in range(6)]
    search, reader = make(rows)

    found = await search.execute(actor(), "  two\n words ", 3)

    user, query, vector, asked = reader.calls[0]
    assert (user, query, asked) == (ME, "two words", 12)
    assert vector is not None and len(found) == 3


async def test_no_embeddings_means_words_only_and_blank_query_is_empty() -> None:
    """Search by words alone works; an empty query asks nothing."""
    search, reader = make([cand("a", owner=ME)], embeddings=False)

    assert len(await search.execute(actor(), "q", 5)) == 1
    assert reader.calls[0][2] is None
    assert await search.execute(actor(), "   ", 5) == []
    assert len(reader.calls) == 1
