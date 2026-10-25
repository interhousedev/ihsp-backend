"""NB-4, NB-8: the queries behind `notebooks.sweep_stuck`, and `save` keeping times."""

from datetime import timedelta

from app.modules.notebooks.domain.enums import (
    ArtifactStatus,
    SourceStatus,
    SummaryStatus,
)
from app.modules.notebooks.infrastructure.uow import SqlNotebooksUnitOfWork
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from app.shared.db.uow_testing import noop_audit_writer, noop_outbox_writer
from app.shared.ids import new_id
from tests.factories.notebooks import (
    NOW,
    make_artifact,
    make_notebook,
    make_source,
    new_notebook_entity,
)

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

CUTOFF = NOW - timedelta(minutes=10)
OLD = NOW - timedelta(hours=1)


async def test_stuck_summaries_are_live_notebooks_building_since_before_the_cutoff(
    uow_factory: UowFactory, student: Actor
) -> None:
    """NB-4: oldest first; fresh, deleted and non-building notebooks are skipped."""
    older = await make_notebook(
        uow_factory,
        student.user_id,
        summary_status=SummaryStatus.BUILDING,
        updated_at=OLD - timedelta(hours=1),
    )
    old = await make_notebook(
        uow_factory,
        student.user_id,
        summary_status=SummaryStatus.BUILDING,
        updated_at=OLD,
    )
    for fields in (
        {"summary_status": SummaryStatus.BUILDING, "updated_at": NOW},
        {"summary_status": SummaryStatus.BUILDING, "updated_at": CUTOFF},
        {
            "summary_status": SummaryStatus.BUILDING,
            "updated_at": OLD,
            "deleted_at": NOW,
        },
        {"summary_status": SummaryStatus.STALE, "updated_at": OLD},
        {"summary_status": SummaryStatus.READY, "updated_at": OLD},
    ):
        await make_notebook(uow_factory, student.user_id, **fields)

    async with uow_factory() as uow:
        found = await uow.notebooks.stuck_summaries(CUTOFF, limit=10)
        limited = await uow.notebooks.stuck_summaries(CUTOFF, limit=1)

    assert [n.id for n in found] == [older.id, old.id]
    assert [n.id for n in limited] == [older.id]


async def test_stuck_summaries_skip_rows_locked_by_another_worker(
    engine: AsyncEngine,
) -> None:
    """NB-4: the sweep never waits for a summary that is being built right now."""
    maker = async_sessionmaker(engine, expire_on_commit=False)

    def open_uow() -> SqlNotebooksUnitOfWork:
        return SqlNotebooksUnitOfWork(maker, noop_outbox_writer, noop_audit_writer)

    owner = new_id()
    first = new_notebook_entity(
        owner, summary_status=SummaryStatus.BUILDING, updated_at=OLD
    )
    second = new_notebook_entity(
        owner, summary_status=SummaryStatus.BUILDING, updated_at=OLD
    )
    async with open_uow() as uow:
        await uow.notebooks.add(first)
        await uow.notebooks.add(second)
        await uow.commit()
    try:
        async with open_uow() as worker, open_uow() as sweeper:
            held = await worker.notebooks.stuck_summaries(CUTOFF, limit=1)
            swept = await sweeper.notebooks.stuck_summaries(CUTOFF, limit=10)
        assert len(held) == 1
        assert held[0].id not in {n.id for n in swept}
        assert {first.id, second.id} - {held[0].id} == {n.id for n in swept}
    finally:
        async with open_uow() as uow:
            await uow.notebooks.hard_delete([first.id, second.id])
            await uow.commit()


async def test_stuck_queued_are_live_queued_outputs_not_updated_since_the_cutoff(
    uow_factory: UowFactory, student: Actor
) -> None:
    """NB-8: oldest first; fresh, deleted and started outputs are skipped."""
    notebook = await make_notebook(uow_factory, student.user_id)
    older = await make_artifact(
        uow_factory,
        notebook,
        status=ArtifactStatus.QUEUED,
        updated_at=OLD - timedelta(hours=1),
    )
    old = await make_artifact(
        uow_factory, notebook, status=ArtifactStatus.QUEUED, updated_at=OLD
    )
    await make_artifact(
        uow_factory, notebook, status=ArtifactStatus.QUEUED, updated_at=NOW
    )
    await make_artifact(
        uow_factory, notebook, status=ArtifactStatus.QUEUED, updated_at=CUTOFF
    )
    await make_artifact(
        uow_factory,
        notebook,
        status=ArtifactStatus.QUEUED,
        updated_at=OLD,
        deleted_at=NOW,
    )
    for status in (
        ArtifactStatus.GENERATING,
        ArtifactStatus.READY,
        ArtifactStatus.FAILED,
        ArtifactStatus.CANCELED,
    ):
        await make_artifact(uow_factory, notebook, status=status, updated_at=OLD)

    async with uow_factory() as uow:
        found = await uow.artifacts.stuck_queued(CUTOFF, limit=10)
        limited = await uow.artifacts.stuck_queued(CUTOFF, limit=1)

    assert [a.id for a in found] == [older.id, old.id]
    assert [a.id for a in limited] == [older.id]


async def test_save_writes_updated_at_as_given_even_when_it_did_not_change(
    uow_factory: UowFactory, student: Actor
) -> None:
    """NB-3: the column's `onupdate` must not replace an unchanged `updated_at`."""
    notebook = await make_notebook(uow_factory, student.user_id)
    source = await make_source(uow_factory, notebook)
    artifact = await make_artifact(uow_factory, notebook)

    async with uow_factory() as uow:
        notebook.last_opened_at = NOW
        source.title = "Renamed"
        artifact.title = "Renamed"
        await uow.notebooks.save(notebook)
        await uow.sources.save(source)
        await uow.artifacts.save(artifact)
        await uow.commit()

    async with uow_factory() as uow:
        stored = await uow.notebooks.get(notebook.id)
        assert stored is not None
        assert stored.last_opened_at == NOW
        assert stored.updated_at == notebook.updated_at
        assert (await uow.sources.get(source.id)) == source
        assert (await uow.artifacts.get(artifact.id)) == artifact
        assert notebook.updated_at == source.updated_at == artifact.updated_at == NOW


async def test_stuck_processing_returns_pending_and_processing_sources(
    uow_factory: UowFactory, student: Actor
) -> None:
    """NB-4: the existing source query covers both unfinished statuses."""
    notebook = await make_notebook(uow_factory, student.user_id)
    pending = await make_source(
        uow_factory, notebook, status=SourceStatus.PENDING, texts=(), updated_at=OLD
    )
    processing = await make_source(
        uow_factory, notebook, status=SourceStatus.PROCESSING, texts=(), updated_at=OLD
    )
    await make_source(uow_factory, notebook, status=SourceStatus.READY, updated_at=OLD)

    async with uow_factory() as uow:
        found = await uow.sources.stuck_processing(CUTOFF, limit=10)

    assert {s.id for s in found} == {pending.id, processing.id}
