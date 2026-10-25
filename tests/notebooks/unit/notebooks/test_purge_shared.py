"""NB-AUTO: `notebooks.purge_shared` drops texts and cached results nobody uses."""

from datetime import UTC, datetime, timedelta

from app.modules.notebooks.application.purge_shared import PurgeShared
from app.modules.notebooks.domain.entities import (
    CachedArtifact,
    CachedSummary,
    Notebook,
    NotebookSummary,
)
from app.modules.notebooks.domain.enums import ArtifactKind
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from tests.factories.notebooks import drafts_from_texts, make_notebook, make_source
from tests.fakes.clock import FixedClock

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

KEY = "k" * 64


async def _keep_in_cache(uow_factory: UowFactory) -> None:
    async with uow_factory() as uow:
        await uow.shared.save_summary(
            KEY,
            "en",
            CachedSummary(
                "T", None, NotebookSummary(summary="S", generated_at=datetime.now(UTC))
            ),
        )
        await uow.shared.save_artifact(
            CachedArtifact(
                cache_key=KEY,
                kind=ArtifactKind.QUIZ,
                title="Quiz",
                format=None,
                content={"questions": []},
                refs_index=None,
                source_map={},
                source_documents={},
                options={},
                sampled=False,
                model=None,
            )
        )
        await uow.commit()


async def _age(session: AsyncSession, clock: FixedClock, days: int) -> None:
    """Make every shared row `days` days older than the clock."""
    for table in ("documents", "shared_summaries", "shared_artifacts"):
        await session.execute(
            text(f"UPDATE notebooks.{table} SET created_at = :at"),  # noqa: S608
            {"at": clock.now() - timedelta(days=days)},
        )


@pytest.fixture
async def notebook(uow_factory: UowFactory, student: Actor) -> Notebook:
    """A notebook of the student."""
    return await make_notebook(uow_factory, student.user_id)


@pytest.fixture
def purge(uow_factory: UowFactory, clock: FixedClock) -> PurgeShared:
    """The job over the test database."""
    return PurgeShared(uow_factory=uow_factory, clock=clock)


async def test_a_document_nobody_holds_goes_after_a_day_but_a_held_one_stays(
    purge: PurgeShared,
    uow_factory: UowFactory,
    db_session: AsyncSession,
    clock: FixedClock,
    notebook: Notebook,
) -> None:
    """NB-AUTO: documents of deleted notebooks are removed, in-use ones never."""
    held = await make_source(uow_factory, notebook, texts=("held text",))
    async with uow_factory() as uow:
        orphan = await uow.documents.create(
            "o" * 64,
            drafts_from_texts(("orphan",)),
            word_count=1,
            char_count=6,
            token_estimate=2,
        )
        await uow.commit()
    await _age(db_session, clock, 0)

    assert (await purge.execute())["documents"] == 0  # too new: its source may come

    await _age(db_session, clock, 2)
    result = await purge.execute()

    assert result["documents"] == 1
    async with uow_factory() as uow:
        assert await uow.documents.find_by_hash(orphan.content_hash) is None
        assert await uow.documents.find_by_hash(held.content_hash or "") is not None


async def test_cached_results_unused_for_ninety_days_are_removed(
    purge: PurgeShared,
    uow_factory: UowFactory,
    db_session: AsyncSession,
    clock: FixedClock,
) -> None:
    """NB-AUTO: a cache row that nobody hits expires; a recent one stays."""
    await _keep_in_cache(uow_factory)
    await _age(db_session, clock, 30)
    assert (await purge.execute())["cache"] == 0

    await _age(db_session, clock, 100)
    result = await purge.execute()

    assert result["cache"] == 2
    async with uow_factory() as uow:
        now = datetime.now(UTC)
        assert await uow.shared.get_summary(KEY, "en", now) is None
        assert await uow.shared.get_artifact(KEY, now) is None


async def test_a_cache_row_that_was_hit_lately_stays(
    purge: PurgeShared,
    uow_factory: UowFactory,
    db_session: AsyncSession,
    clock: FixedClock,
) -> None:
    """NB-AUTO: only unused rows expire: a hit renews the row."""
    await _keep_in_cache(uow_factory)
    await _age(db_session, clock, 100)
    async with uow_factory() as uow:
        assert await uow.shared.get_artifact(KEY, datetime.now(UTC)) is not None
        assert await uow.shared.get_summary(KEY, "en", datetime.now(UTC)) is not None
        await uow.commit()

    result = await purge.execute()

    assert result["cache"] == 0
