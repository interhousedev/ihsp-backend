"""NB-8: the Re-read button puts a source back through extraction."""

from app.modules.notebooks.domain.entities import Notebook
from app.modules.notebooks.domain.enums import SourceFailure, SourceStatus
from app.modules.notebooks.domain.errors import NotebookNotFoundError
from app.modules.notebooks.domain.source_input import TextInput, UrlInput
from app.modules.notebooks.ports.transcript import NO_TRANSCRIPT
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.modules.notebooks.wiring_sources import SourcesServices
from app.shared.actor import Actor
from tests.fakes.notebooks.world import World
from tests.fakes.tasks import FakeTaskKicker
from tests.notebooks.unit.sources.support import (
    PROCESS_TASK,
    add_one,
    add_ready,
    passages_of,
    stored,
)

import pytest

ID = "dQw4w9WgXcQ"
URL = f"https://youtu.be/{ID}"


async def test_a_source_without_text_is_read_again_and_becomes_ready(
    sources: SourcesServices,
    uow_factory: UowFactory,
    world: World,
    student: Actor,
    notebook: Notebook,
    kicker: FakeTaskKicker,
) -> None:
    """The failed video is queued, read from its captions once they exist, and ready."""
    world.transcripts.fail(ID, NO_TRANSCRIPT)
    failed = await add_ready(sources, uow_factory, student, notebook, UrlInput(url=URL))
    assert failed.failure is SourceFailure.NO_TRANSCRIPT
    world.transcripts.failures.clear()
    world.transcripts.add_video(ID, [(0.0, "Captions arrived late.")])

    queued = await sources.reread_source.execute(student, notebook.id, failed.id)

    assert (queued.status, queued.failure) == (SourceStatus.PENDING, None)
    assert kicker.calls[-1] == (PROCESS_TASK, {"source_id": str(failed.id)})
    await sources.process_source.execute(failed.id)
    done = await stored(uow_factory, failed.id)
    assert done.status is SourceStatus.READY
    assert "Captions arrived late." in " ".join(
        p.text for p in await passages_of(uow_factory, done.id)
    )


async def test_a_source_still_waiting_or_processing_is_returned_unchanged(
    sources: SourcesServices,
    world: World,
    student: Actor,
    notebook: Notebook,
    uow_factory: UowFactory,
    kicker: FakeTaskKicker,
) -> None:
    """Idempotent: no second job is queued while the source is being read."""
    world.transcripts.fail(ID, NO_TRANSCRIPT)
    pending = await add_one(sources, student, notebook, UrlInput(url=URL))
    queued = len(kicker.calls)

    again = await sources.reread_source.execute(student, notebook.id, pending.id)

    assert again.status is SourceStatus.PENDING
    assert len(kicker.calls) == queued


async def test_only_the_owner_can_reread(
    sources: SourcesServices,
    uow_factory: UowFactory,
    student: Actor,
    other_student: Actor,
    notebook: Notebook,
    their_notebook: Notebook,
) -> None:
    """Another student, or the wrong notebook, gets a 404."""
    ready = await add_ready(
        sources, uow_factory, student, notebook, TextInput(title="Notes", text="Text.")
    )

    with pytest.raises(NotebookNotFoundError):
        await sources.reread_source.execute(other_student, notebook.id, ready.id)
    with pytest.raises(NotebookNotFoundError):
        await sources.reread_source.execute(student, their_notebook.id, ready.id)
