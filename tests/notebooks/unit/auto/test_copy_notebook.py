"""NB-AUTO: "Make a copy" turns any notebook into a normal, editable one."""

from app.modules.notebooks.domain.entities import ChatConfig, Notebook, SourceGuide
from app.modules.notebooks.domain.enums import (
    ChatStyle,
    GuideStatus,
    NotebookOrigin,
    SourceStatus,
    SummaryStatus,
)
from app.modules.notebooks.domain.errors import (
    NotebookLimitError,
    NotebookNotFoundError,
)
from app.modules.notebooks.domain.source_input import TextInput
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.modules.notebooks.wiring_auto import AutoServices
from app.modules.notebooks.wiring_core import NotebooksCore
from app.modules.notebooks.wiring_notebooks import build_notebooks
from app.modules.notebooks.wiring_sources import SourcesServices
from app.shared.actor import Actor
from app.shared.contracts.academic import LessonRef
from tests.factories.notebooks import make_notebook, make_source
from tests.fakes.clock import FixedClock
from tests.fakes.notebooks.world import World
from tests.fakes.tasks import FakeTaskKicker
from tests.notebooks.unit.auto.conftest import open_subject, teacher_file
from tests.notebooks.unit.sources.support import SUMMARY, HookedLlm

import pytest


async def test_the_copy_of_an_auto_notebook_is_a_normal_notebook_with_the_same_sources(
    auto: AutoServices,
    sources: SourcesServices,
    core: NotebooksCore,
    uow_factory: UowFactory,
    world: World,
    student: Actor,
    physics: LessonRef,
) -> None:
    """NB-AUTO: same sources, no re-reading, and nothing syncs into the copy."""
    link = teacher_file(world, physics)
    original = await open_subject(auto, student, physics)
    async with uow_factory() as uow:
        [waiting] = await uow.sources.list_for_notebook(original.id)
    await sources.process_source.execute(waiting.id)
    async with uow_factory() as uow:
        [source] = await uow.sources.list_for_notebook(original.id)
    lifecycle = build_notebooks(core)

    copy = await lifecycle.copy_notebook.execute(student, original.id)

    assert copy.id != original.id
    assert copy.origin is NotebookOrigin.MANUAL and copy.auto_settings is None
    assert copy.subject_id is None and copy.lesson_id is None
    assert copy.title == "Physics (copy)" and not copy.title_auto
    assert copy.space_key == original.space_key
    async with uow_factory() as uow:
        [cloned] = await uow.sources.list_for_notebook(copy.id)
        again = await uow.passages.list_for_sources([source.id])
        same = await uow.passages.list_for_sources([cloned.id])
    assert cloned.id != source.id and cloned.ref_key == f"lesson:{link}"
    assert cloned.document_id == source.document_id is not None
    assert (
        cloned.status is SourceStatus.READY
        and cloned.passage_count == source.passage_count
    )
    assert [p.id for p in again] == [p.id for p in same] != []
    assert copy.source_count == 1 and copy.ready_source_count == 1
    # The copy is free: sources can be added and removed, and a sync does not touch it.
    added = await sources.add_sources.execute(
        student, copy.id, [TextInput(title="Pasted", text="A pasted text.")]
    )
    assert len(added.items) == 1
    await sources.remove_source.execute(student, copy.id, cloned.id)
    assert (await auto.sync_auto_notebook.execute(copy.id)).added == 0


async def test_the_copy_takes_the_chat_settings_and_a_current_summary(
    core: NotebooksCore,
    sources: SourcesServices,
    uow_factory: UowFactory,
    scripted_llm: HookedLlm,
    student: Actor,
    clock: FixedClock,
) -> None:
    """NB-AUTO: the summary is copied when it is up to date, so it is paid once."""
    original = await make_notebook(
        uow_factory,
        student.user_id,
        title="Cells",
        chat_config=ChatConfig(style=ChatStyle.LEARNING_GUIDE),
        summary_status=SummaryStatus.STALE,
        summary_due_at=clock.now(),
    )
    await make_source(
        uow_factory,
        original,
        title="Cells",
        texts=("Cells are the unit of life.",),
        guide=SourceGuide(summary="Cells.", key_topics=["Cell"], questions=["Why?"]),
        guide_status=GuideStatus.READY,
    )
    scripted_llm.queue_json(SUMMARY)
    assert await sources.refresh_summaries.execute() == 1
    lifecycle = build_notebooks(core)
    calls = scripted_llm.calls

    copy = await lifecycle.copy_notebook.execute(student, original.id)

    async with uow_factory() as uow:
        saved = await uow.notebooks.get(original.id)
    assert saved is not None and saved.summary is not None
    assert copy.chat_config.style is ChatStyle.LEARNING_GUIDE
    assert copy.summary == saved.summary
    assert copy.summary_status is SummaryStatus.READY
    assert copy.summary_hash == saved.summary_hash
    assert scripted_llm.calls == calls


async def test_unfinished_sources_are_read_again_in_the_copy(
    core: NotebooksCore,
    sources: SourcesServices,
    uow_factory: UowFactory,
    student: Actor,
    notebook: Notebook,
    kicker: FakeTaskKicker,
) -> None:
    """NB-AUTO: a source still waiting is started again for the copy."""
    waiting = (
        await sources.add_sources.execute(
            student, notebook.id, [TextInput(title="T", text="Not read yet.")]
        )
    ).items[0]
    kicker.calls.clear()
    lifecycle = build_notebooks(core)

    copy = await lifecycle.copy_notebook.execute(student, notebook.id)

    async with uow_factory() as uow:
        [cloned] = await uow.sources.list_for_notebook(copy.id)
    assert cloned.status is SourceStatus.PENDING and cloned.id != waiting.id
    assert ("notebooks.process_source", {"source_id": str(cloned.id)}) in kicker.calls


async def test_only_the_owner_can_copy(
    core: NotebooksCore, other_student: Actor, notebook: Notebook
) -> None:
    """NB-AUTO: someone else's notebook is a 404."""
    lifecycle = build_notebooks(core)

    with pytest.raises(NotebookNotFoundError):
        await lifecycle.copy_notebook.execute(other_student, notebook.id)


async def test_a_copy_counts_against_the_notebook_limit(
    core: NotebooksCore,
    uow_factory: UowFactory,
    student: Actor,
    notebook: Notebook,
) -> None:
    """NB-AUTO: copying cannot get round the 50 notebooks per student."""
    for _ in range(core.deps.settings.notebooks.max_notebooks - 1):
        await make_notebook(uow_factory, student.user_id)
    lifecycle = build_notebooks(core)

    with pytest.raises(NotebookLimitError):
        await lifecycle.copy_notebook.execute(student, notebook.id)
