"""The exemplar repository on PostgreSQL."""

import dataclasses
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

from app.modules.admission.application.exemplar_search import UowExemplarSource
from app.modules.admission.application.exemplars import public_view
from app.modules.admission.domain.exemplars import Exemplar
from app.modules.admission.infrastructure.essay_crypto import (
    AesGcmEssayCipher,
    MemoryEssayKeyStore,
)
from app.modules.admission.infrastructure.exemplars_repository import (
    SqlExemplarRepository,
)
from app.modules.admission.infrastructure.orm.catalog import InstitutionRow
from app.modules.admission.infrastructure.staff_repositories import (
    SqlPrivacyRepository,
)
from app.shared.ids import new_id
from tests.fakes.clock import FixedClock

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

NOW = datetime(2026, 10, 6, 9, 0, tzinfo=UTC)


def _item(title: str, status: str = "draft") -> Exemplar:
    return Exemplar(
        id=new_id(), institution_id=None, school_name="", year=2025,
        kind="personal_statement", prompt="", title=title, body="Some body text",
        word_count=3, source_url="https://e.com/a", source_name="", tags=("a",),
        notes="", status=status, language="en", created_by=None, updated_by=None,
        created_at=NOW, updated_at=NOW, lock_version=0,
    )  # type: ignore[arg-type]  # fmt: skip


async def test_round_trip_search_lock_and_delete(
    sessionmaker_in_tx: async_sessionmaker[AsyncSession],
) -> None:
    """ADM-EXM-11: add, find, filter, update on the lock, delete."""
    async with sessionmaker_in_tx() as s:
        repo = SqlExemplarRepository(s)
        item = _item("Percent_100%")
        await repo.add(item)
        assert await repo.find_by_source(item.source_url, item.title) == item.id
        rows, total = await repo.search(
            status="draft", kind=None, institution_id=None,
            query="percent_", limit=10, offset=0,
        )  # fmt: skip
        assert total == 1 and rows[0].id == item.id
        _, none = await repo.search(
            status=None, kind=None, institution_id=None,
            query="%", limit=10, offset=0,
        )  # fmt: skip
        assert none == 1
        changed = dataclasses.replace(item, status="published")
        assert await repo.update(changed, expected_lock=0)
        assert not await repo.update(changed, expected_lock=0)
        assert [e.id for e in await repo.published()] == [item.id]
        assert await repo.delete(item.id)
        assert not await repo.delete(item.id)


def _source(s: AsyncSession) -> UowExemplarSource:
    @asynccontextmanager
    async def uow():  # type: ignore[no-untyped-def]
        yield SimpleNamespace(exemplars=SqlExemplarRepository(s))

    return UowExemplarSource(uow, FixedClock(NOW))  # type: ignore[arg-type]


async def _institution(s: AsyncSession) -> UUID:
    row = InstitutionRow(id=new_id(), name="Uni " + str(new_id()), country="GB")
    s.add(row)
    await s.flush()
    return row.id


async def test_archive_leaves_the_published_set(
    sessionmaker_in_tx: async_sessionmaker[AsyncSession],
) -> None:
    """ADM-EXM-SQL-1: create, update and archive; archived is not published."""
    async with sessionmaker_in_tx() as s:
        repo = SqlExemplarRepository(s)
        item = dataclasses.replace(_item("A", "published"), body="alpha beta")
        await repo.add(item)
        assert (await repo.get(item.id)) is not None
        edited = dataclasses.replace(item, title="A2", notes="n")
        assert await repo.update(edited, expected_lock=0)
        got = await repo.get(item.id)
        assert got is not None and got.title == "A2" and got.lock_version == 1
        archived = dataclasses.replace(got, status="archived")
        assert await repo.update(archived, expected_lock=1)
        assert await repo.published() == []
        rows, total = await repo.search(
            status="archived", kind=None, institution_id=None,
            query=None, limit=10, offset=0,
        )  # fmt: skip
        assert total == 1 and rows[0].id == item.id


async def test_closest_ranks_nearest_published_and_skips_others(
    sessionmaker_in_tx: async_sessionmaker[AsyncSession],
) -> None:
    """ADM-EXM-SQL-2: closest(k=3) orders by similarity, published only."""
    async with sessionmaker_in_tx() as s:
        repo = SqlExemplarRepository(s)
        texts = {
            "cats": "cats purr softly and sleep on warm windows",
            "boats": "boats sail across stormy oceans with heavy sails",
            "rocks": "granite rocks erode slowly under river water",
            "draft": "cats purr softly and sleep on warm windows",
        }
        ids = {}
        for name, text in texts.items():
            item = dataclasses.replace(
                _item(name, "draft" if name == "draft" else "published"),
                body=text, word_count=len(text.split()),
            )  # fmt: skip
            ids[name] = item.id
            await repo.add(item)
        got = await _source(s).closest(
            kind="personal_statement", prompt="",
            body="cats purr and sleep on windows", institution_id=None, k=3,
        )  # fmt: skip
        assert len(got) == 3
        assert got[0].exemplar.id == ids["cats"]
        assert ids["draft"] not in {m.exemplar.id for m in got}
        assert got[0].similarity >= got[1].similarity >= got[2].similarity


async def test_institution_filter_and_boost(
    sessionmaker_in_tx: async_sessionmaker[AsyncSession],
) -> None:
    """ADM-EXM-SQL-3: search filters by institution; closest prefers its own."""
    async with sessionmaker_in_tx() as s:
        repo = SqlExemplarRepository(s)
        inst = await _institution(s)
        same = dataclasses.replace(
            _item("same", "published"), institution_id=inst, body="shared words here"
        )
        other = dataclasses.replace(
            _item("other", "published"), body="shared words here"
        )
        await repo.add(same)
        await repo.add(other)
        rows, total = await repo.search(
            status=None, kind=None, institution_id=inst,
            query=None, limit=10, offset=0,
        )  # fmt: skip
        assert total == 1 and rows[0].id == same.id
        got = await _source(s).closest(
            kind="personal_statement", prompt="", body="shared words here",
            institution_id=inst, k=3,
        )  # fmt: skip
        assert [m.exemplar.id for m in got][0] == same.id


async def test_student_listing_is_excerpt_and_link_only(
    sessionmaker_in_tx: async_sessionmaker[AsyncSession],
) -> None:
    """ADM-EXM-SQL-4: students get published 80-word excerpts and the link."""
    async with sessionmaker_in_tx() as s:
        repo = SqlExemplarRepository(s)
        body = " ".join(f"w{i}" for i in range(200))
        pub = dataclasses.replace(_item("pub", "published"), body=body, word_count=200)
        await repo.add(pub)
        await repo.add(_item("hidden", "draft"))
        rows, total = await repo.search(
            status="published", kind=None, institution_id=None,
            query=None, limit=10, offset=0,
        )  # fmt: skip
        assert total == 1
        view = public_view(rows[0])
        assert view.excerpt.endswith("…")
        assert len(view.excerpt.rstrip("…").split()) == 80
        assert view.source_url == pub.source_url
        assert not hasattr(view, "body")


async def test_privacy_erase_nulls_author_columns(
    sessionmaker_in_tx: async_sessionmaker[AsyncSession],
) -> None:
    """ADM-EXM-SQL-5: erasing a user clears created_by/updated_by, keeps rows."""
    async with sessionmaker_in_tx() as s:
        repo = SqlExemplarRepository(s)
        author, other = new_id(), new_id()
        mine = dataclasses.replace(_item("mine"), created_by=author, updated_by=author)
        theirs = dataclasses.replace(
            _item("theirs"), created_by=other, updated_by=other
        )
        await repo.add(mine)
        await repo.add(theirs)
        privacy = SqlPrivacyRepository(s, AesGcmEssayCipher(MemoryEssayKeyStore()))
        counts = await privacy.erase(author)
        assert counts["exemplar_essays"] >= 1
        s.expire_all()
        got = await repo.get(mine.id)
        assert got is not None
        assert got.created_by is None and got.updated_by is None
        kept = await repo.get(theirs.id)
        assert kept is not None and kept.created_by == other
