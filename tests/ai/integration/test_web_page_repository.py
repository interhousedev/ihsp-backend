"""Stored web pages in PostgreSQL: upsert, vector search by meaning, cache and purge."""

from datetime import UTC, datetime, timedelta

from app.modules.ai.application.web_pages import text_hash
from app.modules.ai.infrastructure.fake_embeddings import fake_vector
from app.modules.ai.infrastructure.repositories.web_page_repository import (
    SqlWebPageRepository,
)
from app.modules.ai.ports.web_pages import PageRecord
from app.shared.db.embeddings import Embedding

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

NOW = datetime(2026, 10, 6, 9, 0, tzinfo=UTC)
MODEL = "test-embedding"


def record(n: int, text: str) -> PageRecord:
    """A page record whose content hash is the hash of its text."""
    return PageRecord(
        url=f"https://site{n}.example.org/page",
        site=f"site{n}.example.org",
        title=f"Page {n}",
        text=text,
        highlight="",
        published_date=None,
        content_hash=text_hash(text),
    )


async def store_vector(session: AsyncSession, text: str) -> None:
    """Store the fake vector of a text in `vectors.embeddings`."""
    session.add(
        Embedding(
            content_hash=text_hash(text),
            model=MODEL,
            dims=1024,
            embedding=fake_vector(text),
        )
    )
    await session.flush()


async def test_a_known_url_is_one_row_seen_again(
    sessionmaker_in_tx: async_sessionmaker[AsyncSession],
) -> None:
    async with sessionmaker_in_tx() as session:
        repo = SqlWebPageRepository(session)
        first = await repo.upsert([record(1, "cells make food")], NOW)
        later = NOW + timedelta(days=10)
        again = await repo.upsert([record(1, "cells make food")], later)

        assert first == again  # the same page, the same id
        [page] = await repo.pages(list(first.values()))
        assert page.url == "https://site1.example.org/page"
        assert page.title == "Page 1"


async def test_the_nearest_pages_by_meaning_respect_the_threshold(
    sessionmaker_in_tx: async_sessionmaker[AsyncSession],
) -> None:
    close = "photosynthesis uses light energy in plants"
    far = "volcanoes erupt molten lava from the mantle"
    async with sessionmaker_in_tx() as session:
        repo = SqlWebPageRepository(session)
        ids = await repo.upsert([record(1, close), record(2, far)], NOW)
        await store_vector(session, close)
        await store_vector(session, far)

        query = fake_vector("light energy and photosynthesis in plants")
        found = await repo.nearest(MODEL, query, 10, 0.3)
        assert [page_id for page_id, _ in found][:1] == [
            ids["https://site1.example.org/page"]
        ]
        assert all(similarity >= 0.3 for _, similarity in found)

        strict = await repo.nearest(MODEL, query, 10, 0.999)
        assert strict == []
        assert await repo.nearest("another-model", query, 10, 0.3) == []


async def test_the_cached_answer_of_a_query_is_its_order_within_the_window(
    sessionmaker_in_tx: async_sessionmaker[AsyncSession],
) -> None:
    async with sessionmaker_in_tx() as session:
        repo = SqlWebPageRepository(session)
        ids = list((await repo.upsert([record(1, "a"), record(2, "b")], NOW)).values())
        await repo.put_query("key-1", "a question", [ids[1], ids[0]], NOW)

        assert await repo.cached("key-1", NOW - timedelta(days=1)) == [ids[1], ids[0]]
        assert await repo.cached("key-1", NOW + timedelta(days=1)) is None
        assert await repo.cached("missing", NOW - timedelta(days=1)) is None


async def test_expired_pages_and_answers_go_with_their_vectors(
    sessionmaker_in_tx: async_sessionmaker[AsyncSession],
) -> None:
    old_text = "an old lesson about cells"
    kept_text = "a lesson about rivers that is seen again"
    cutoff = NOW - timedelta(days=183)
    async with sessionmaker_in_tx() as session:
        repo = SqlWebPageRepository(session)
        await repo.upsert([record(1, old_text)], NOW - timedelta(days=400))
        await repo.upsert([record(2, kept_text)], NOW - timedelta(days=400))
        await store_vector(session, old_text)
        await store_vector(session, kept_text)
        await repo.upsert([record(2, kept_text)], NOW)  # returned again: last seen now
        await repo.put_query("old", "old question", [], NOW - timedelta(days=400))
        await repo.put_query("new", "new question", [], NOW)

        pages, vectors = await repo.purge_pages(cutoff, 500)
        queries = await repo.purge_queries(NOW - timedelta(days=183), 500)

        assert (pages, vectors, queries) == (1, 1, 1)
        remaining = (await session.execute(select(Embedding.content_hash))).scalars()
        assert set(remaining) == {text_hash(kept_text)}
        assert await repo.cached("old", NOW - timedelta(days=500)) is None
        assert await repo.cached("new", NOW - timedelta(days=1)) == []
        kept = await repo.upsert([record(2, kept_text)], NOW)
        assert len(kept) == 1
        assert await repo.pages(list(kept.values()))


async def test_a_purge_works_in_batches_and_keeps_a_vector_still_in_use(
    sessionmaker_in_tx: async_sessionmaker[AsyncSession],
) -> None:
    shared_text = "the same text on two old pages"
    async with sessionmaker_in_tx() as session:
        repo = SqlWebPageRepository(session)
        old = NOW - timedelta(days=400)
        await repo.upsert([record(1, shared_text), record(2, shared_text)], old)
        await store_vector(session, shared_text)
        await repo.upsert([record(2, shared_text)], NOW)  # page 2 stays

        pages, vectors = await repo.purge_pages(NOW - timedelta(days=183), 1)

        assert (pages, vectors) == (1, 0)  # one page of the batch; its text still used
        assert (
            await session.execute(select(Embedding.content_hash))
        ).scalars().all() == [text_hash(shared_text)]
