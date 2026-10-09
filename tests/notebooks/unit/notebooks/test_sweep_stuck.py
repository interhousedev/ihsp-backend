"""NB-4, NB-8: `notebooks.sweep_stuck` unsticks sources, outputs and summaries."""

from datetime import datetime, timedelta

from app.modules.notebooks.domain.entities import Notebook
from app.modules.notebooks.domain.enums import (
    ArtifactKind,
    ArtifactStatus,
    SourceStatus,
    SummaryStatus,
)
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.modules.notebooks.wiring_core import NotebooksCore
from app.modules.notebooks.wiring_notebooks import NotebooksLifecycleServices
from app.shared.actor import Actor
from tests.factories.notebooks import make_artifact, make_notebook, make_source
from tests.fakes.clock import FixedClock
from tests.fakes.tasks import FakeTaskKicker

import pytest

NOTHING = {
    "sources": 0,
    "artifacts_failed": 0,
    "artifacts_requeued": 0,
    "summaries": 0,
}


@pytest.fixture
async def notebook(uow_factory: UowFactory, student: Actor) -> Notebook:
    """A notebook of the student."""
    return await make_notebook(uow_factory, student.user_id)


def _ago(clock: FixedClock, **delta: float) -> datetime:
    return clock.now() - timedelta(**delta)


async def test_nothing_stuck_changes_nothing(
    lifecycle: NotebooksLifecycleServices, kicker: FakeTaskKicker
) -> None:
    """NB-4: an empty system gives zero counts for every category."""
    assert await lifecycle.sweep_stuck.execute() == NOTHING
    assert kicker.calls == []


@pytest.mark.parametrize("status", [SourceStatus.PENDING, SourceStatus.PROCESSING])
async def test_source_not_updated_for_10_minutes_is_kicked_again(
    lifecycle: NotebooksLifecycleServices,
    uow_factory: UowFactory,
    notebook: Notebook,
    kicker: FakeTaskKicker,
    clock: FixedClock,
    status: SourceStatus,
) -> None:
    """NB-4: the job `notebooks.process_source` is started once more."""
    source = await make_source(
        uow_factory,
        notebook,
        status=status,
        texts=(),
        updated_at=_ago(clock, minutes=11),
    )

    counts = await lifecycle.sweep_stuck.execute()

    assert counts["sources"] == 1
    assert kicker.calls == [("notebooks.process_source", {"source_id": str(source.id)})]
    async with uow_factory() as uow:
        stored = await uow.sources.get(source.id)
    assert stored is not None
    assert stored.updated_at == clock.now()
    assert stored.status is status


async def test_sources_that_are_fresh_or_finished_are_left_alone(
    lifecycle: NotebooksLifecycleServices,
    uow_factory: UowFactory,
    notebook: Notebook,
    kicker: FakeTaskKicker,
    clock: FixedClock,
) -> None:
    """NB-4: only pending and processing sources older than 10 minutes qualify."""
    old = _ago(clock, hours=3)
    await make_source(
        uow_factory,
        notebook,
        status=SourceStatus.PROCESSING,
        texts=(),
        updated_at=_ago(clock, minutes=9),
    )
    for status in (SourceStatus.READY, SourceStatus.FAILED, SourceStatus.STALE):
        await make_source(uow_factory, notebook, status=status, updated_at=old)
    await make_source(
        uow_factory, notebook, status=SourceStatus.UNAVAILABLE, updated_at=old
    )

    counts = await lifecycle.sweep_stuck.execute()

    assert counts == NOTHING
    assert kicker.calls == []


async def test_a_rekicked_source_waits_another_10_minutes_before_the_next_kick(
    lifecycle: NotebooksLifecycleServices,
    uow_factory: UowFactory,
    notebook: Notebook,
    kicker: FakeTaskKicker,
    clock: FixedClock,
) -> None:
    """NB-4: running the job twice kicks once; later it may kick again."""
    await make_source(
        uow_factory,
        notebook,
        status=SourceStatus.PENDING,
        texts=(),
        updated_at=_ago(clock, minutes=30),
    )

    first = await lifecycle.sweep_stuck.execute()
    second = await lifecycle.sweep_stuck.execute()
    clock.advance(minutes=9)
    third = await lifecycle.sweep_stuck.execute()
    clock.advance(minutes=2)
    fourth = await lifecycle.sweep_stuck.execute()

    assert (first["sources"], second["sources"], third["sources"]) == (1, 0, 0)
    assert fourth["sources"] == 1
    assert kicker.names() == ["notebooks.process_source"] * 2


async def test_timed_out_output_fails_with_a_timeout_error(
    lifecycle: NotebooksLifecycleServices,
    uow_factory: UowFactory,
    notebook: Notebook,
    clock: FixedClock,
) -> None:
    """NB-8: generating for over 15 minutes becomes `failed(timeout)`."""
    artifact = await make_artifact(
        uow_factory,
        notebook,
        ArtifactKind.QUIZ,
        ArtifactStatus.GENERATING,
        started_at=_ago(clock, minutes=16),
    )

    counts = await lifecycle.sweep_stuck.execute()

    assert counts["artifacts_failed"] == 1
    async with uow_factory() as uow:
        stored = await uow.artifacts.get(artifact.id)
    assert stored is not None
    assert stored.status is ArtifactStatus.FAILED
    assert stored.error is not None
    assert stored.error.code == "timeout"
    assert stored.error.message_key == "notebooks-artifact-error-timeout"
    assert stored.finished_at == clock.now()
    assert stored.updated_at == clock.now()


async def test_timeout_frees_the_running_slot_and_is_not_counted_in_the_quota(
    lifecycle: NotebooksLifecycleServices,
    core: NotebooksCore,
    uow_factory: UowFactory,
    notebook: Notebook,
    student: Actor,
    clock: FixedClock,
) -> None:
    """NB-8, NB-14: the output stops running and its daily count is given back."""
    stuck = await make_artifact(
        uow_factory,
        notebook,
        ArtifactKind.SLIDES,
        ArtifactStatus.GENERATING,
        started_at=_ago(clock, minutes=20),
    )
    healthy = await make_artifact(
        uow_factory,
        notebook,
        ArtifactKind.REPORT,
        ArtifactStatus.GENERATING,
        started_at=_ago(clock, minutes=2),
    )
    owner = student.user_id
    await core.quota.reserve(owner, ArtifactKind.SLIDES, stuck.id)
    await core.quota.reserve(owner, ArtifactKind.REPORT, healthy.id)
    assert await core.quota.running_count(owner) == 2

    await lifecycle.sweep_stuck.execute()
    await lifecycle.sweep_stuck.execute()

    quotas = await core.quota.snapshot(owner)
    assert await core.quota.running_count(owner) == 1
    assert quotas["artifacts"].used == 1
    assert quotas["slides"].used == 0


async def test_outputs_that_are_young_or_not_generating_are_left_alone(
    lifecycle: NotebooksLifecycleServices,
    uow_factory: UowFactory,
    notebook: Notebook,
    kicker: FakeTaskKicker,
    clock: FixedClock,
) -> None:
    """NB-8: 14 minutes is fine; ready, failed and canceled outputs stay as they are."""
    young = await make_artifact(
        uow_factory,
        notebook,
        status=ArtifactStatus.GENERATING,
        started_at=_ago(clock, minutes=14),
    )
    finished = [
        await make_artifact(
            uow_factory,
            notebook,
            status=status,
            started_at=_ago(clock, hours=2),
            updated_at=_ago(clock, hours=2),
        )
        for status in (
            ArtifactStatus.READY,
            ArtifactStatus.FAILED,
            ArtifactStatus.CANCELED,
        )
    ]

    counts = await lifecycle.sweep_stuck.execute()

    assert counts == NOTHING
    async with uow_factory() as uow:
        assert (await uow.artifacts.get(young.id)) == young
        for artifact in finished:
            assert (await uow.artifacts.get(artifact.id)) == artifact
    assert kicker.calls == []


async def test_output_still_queued_after_15_minutes_is_kicked_again_once_per_period(
    lifecycle: NotebooksLifecycleServices,
    uow_factory: UowFactory,
    notebook: Notebook,
    kicker: FakeTaskKicker,
    clock: FixedClock,
) -> None:
    """NB-8: `generate_artifact` is started again; running twice kicks once."""
    artifact = await make_artifact(
        uow_factory,
        notebook,
        status=ArtifactStatus.QUEUED,
        updated_at=_ago(clock, minutes=16),
    )
    await make_artifact(
        uow_factory,
        notebook,
        status=ArtifactStatus.QUEUED,
        updated_at=_ago(clock, minutes=5),
    )
    await make_artifact(
        uow_factory,
        notebook,
        status=ArtifactStatus.QUEUED,
        updated_at=_ago(clock, hours=1),
        deleted_at=_ago(clock, minutes=30),
    )

    first = await lifecycle.sweep_stuck.execute()
    second = await lifecycle.sweep_stuck.execute()

    assert first["artifacts_requeued"] == 1
    assert second == NOTHING
    assert kicker.calls == [
        ("notebooks.generate_artifact", {"artifact_id": str(artifact.id)})
    ]
    async with uow_factory() as uow:
        stored = await uow.artifacts.get(artifact.id)
    assert stored is not None
    assert stored.status is ArtifactStatus.QUEUED
    assert stored.updated_at == clock.now()


async def test_summary_stuck_in_building_goes_back_to_stale_and_due(
    lifecycle: NotebooksLifecycleServices,
    uow_factory: UowFactory,
    student: Actor,
    clock: FixedClock,
) -> None:
    """NB-4: after 10 minutes the summary job runs again at the next minute."""
    stuck = await make_notebook(
        uow_factory,
        student.user_id,
        summary_status=SummaryStatus.BUILDING,
        updated_at=_ago(clock, minutes=11),
    )

    counts = await lifecycle.sweep_stuck.execute()

    assert counts["summaries"] == 1
    async with uow_factory() as uow:
        stored = await uow.notebooks.get(stuck.id)
        due = await uow.notebooks.due_summaries(clock.now(), limit=10)
    assert stored is not None
    assert stored.summary_status is SummaryStatus.STALE
    assert stored.summary_due_at == clock.now()
    assert stored.updated_at == clock.now()
    assert [n.id for n in due] == [stuck.id]


async def test_summaries_that_are_fresh_deleted_or_in_other_states_stay(
    lifecycle: NotebooksLifecycleServices,
    uow_factory: UowFactory,
    student: Actor,
    clock: FixedClock,
) -> None:
    """NB-4: only live notebooks building for over 10 minutes are reset."""
    old = _ago(clock, hours=1)
    kept = [
        await make_notebook(
            uow_factory,
            student.user_id,
            summary_status=SummaryStatus.BUILDING,
            updated_at=_ago(clock, minutes=9),
        ),
        await make_notebook(
            uow_factory,
            student.user_id,
            summary_status=SummaryStatus.BUILDING,
            updated_at=old,
            deleted_at=old,
        ),
        await make_notebook(
            uow_factory,
            student.user_id,
            summary_status=SummaryStatus.READY,
            updated_at=old,
        ),
        await make_notebook(
            uow_factory,
            student.user_id,
            summary_status=SummaryStatus.STALE,
            summary_due_at=old,
            updated_at=old,
        ),
    ]

    counts = await lifecycle.sweep_stuck.execute()

    assert counts == NOTHING
    async with uow_factory() as uow:
        for notebook in kept:
            assert (await uow.notebooks.get(notebook.id)) == notebook


async def test_one_run_handles_every_category_and_a_second_run_does_nothing(
    lifecycle: NotebooksLifecycleServices,
    core: NotebooksCore,
    uow_factory: UowFactory,
    notebook: Notebook,
    student: Actor,
    kicker: FakeTaskKicker,
    clock: FixedClock,
) -> None:
    """NB-4, NB-8: all four sweeps in one run; the job is idempotent."""
    await make_source(
        uow_factory,
        notebook,
        status=SourceStatus.PROCESSING,
        texts=(),
        updated_at=_ago(clock, minutes=40),
    )
    timed_out = await make_artifact(
        uow_factory,
        notebook,
        status=ArtifactStatus.GENERATING,
        started_at=_ago(clock, minutes=40),
    )
    await core.quota.reserve(student.user_id, ArtifactKind.REPORT, timed_out.id)
    await make_artifact(
        uow_factory,
        notebook,
        status=ArtifactStatus.QUEUED,
        updated_at=_ago(clock, minutes=40),
    )
    await make_notebook(
        uow_factory,
        student.user_id,
        summary_status=SummaryStatus.BUILDING,
        updated_at=_ago(clock, minutes=40),
    )

    first = await lifecycle.sweep_stuck.execute()
    second = await lifecycle.sweep_stuck.execute()

    assert first == {
        "sources": 1,
        "artifacts_failed": 1,
        "artifacts_requeued": 1,
        "summaries": 1,
    }
    assert second == NOTHING
    assert sorted(kicker.names()) == [
        "notebooks.generate_artifact",
        "notebooks.process_source",
    ]
