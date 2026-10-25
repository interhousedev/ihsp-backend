"""G12/G13: `POST labels/auto` marks the run and queues the job."""

from app.modules.notebooks.domain.entities import Notebook, Source
from app.modules.notebooks.domain.enums import SourceStatus
from app.modules.notebooks.domain.errors import NotebookNotFoundError
from app.modules.notebooks.domain.label_errors import (
    LabelsNothingToLabelError,
    LabelsRunningError,
)
from app.modules.notebooks.domain.labels import LabelRunStatus
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.modules.notebooks.wiring_labels import LabelsServices
from app.shared.actor import Actor
from tests.factories.notebooks import make_source
from tests.fakes.clock import FixedClock
from tests.fakes.tasks import FakeTaskKicker
from tests.notebooks.unit.labels.support import LABELS_TASK, run_of

import pytest


async def test_a_run_starts_and_the_job_is_queued_after_the_commit(
    labels: LabelsServices,
    uow_factory: UowFactory,
    kicker: FakeTaskKicker,
    student: Actor,
    notebook: Notebook,
    source: Source,
) -> None:
    """G12: status running, who clicked, one `notebooks.label_sources` job."""
    run = await labels.start_labeling.execute(student, notebook.id)

    assert run.status is LabelRunStatus.RUNNING
    stored = await run_of(uow_factory, notebook.id)
    assert (stored.status, stored.started_by) == (
        LabelRunStatus.RUNNING,
        student.user_id,
    )
    assert kicker.calls == [(LABELS_TASK, {"notebook_id": str(notebook.id)})]


async def test_a_second_start_while_running_is_a_conflict(
    labels: LabelsServices,
    kicker: FakeTaskKicker,
    student: Actor,
    notebook: Notebook,
    source: Source,
) -> None:
    """G12: `notebooks/labels-running`, no second job."""
    await labels.start_labeling.execute(student, notebook.id)

    with pytest.raises(LabelsRunningError) as error:
        await labels.start_labeling.execute(student, notebook.id)

    assert error.value.code == "notebooks/labels-running"
    assert len(kicker.calls) == 1


async def test_a_run_that_never_ended_can_be_started_again(
    labels: LabelsServices,
    clock: FixedClock,
    kicker: FakeTaskKicker,
    student: Actor,
    notebook: Notebook,
    source: Source,
) -> None:
    """G12: a lost job (older than 10 minutes) does not block the notebook."""
    await labels.start_labeling.execute(student, notebook.id)
    clock.advance(minutes=11)

    run = await labels.start_labeling.execute(student, notebook.id)

    assert run.status is LabelRunStatus.RUNNING
    assert len(kicker.calls) == 2


async def test_a_notebook_without_a_selected_ready_source_has_nothing_to_label(
    labels: LabelsServices,
    uow_factory: UowFactory,
    kicker: FakeTaskKicker,
    student: Actor,
    notebook: Notebook,
) -> None:
    """G12: empty, unselected and pending sources are `labels-nothing-to-label`."""
    await make_source(uow_factory, notebook, selected=False)
    await make_source(uow_factory, notebook, status=SourceStatus.PENDING, texts=())

    with pytest.raises(LabelsNothingToLabelError) as error:
        await labels.start_labeling.execute(student, notebook.id)

    assert error.value.code == "notebooks/labels-nothing-to-label"
    assert kicker.calls == []


async def test_another_students_notebook_cannot_be_labeled(
    labels: LabelsServices, student: Actor, their_notebook: Notebook
) -> None:
    """G12: 404."""
    with pytest.raises(NotebookNotFoundError):
        await labels.start_labeling.execute(student, their_notebook.id)
