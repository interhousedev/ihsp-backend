"""NB-FC: the hidden notebook that feeds "Add new questions with AI" of a card set."""

from uuid import UUID

from app.modules.notebooks.application.flashcard_workspace import (
    OpenFlashcardWorkspace,
)
from app.modules.notebooks.application.list_notebooks import ListNotebooks
from app.modules.notebooks.domain.entities import Notebook
from app.modules.notebooks.domain.enums import (
    NotebookOrigin,
    SourceStatus,
    SummaryStatus,
)
from app.modules.notebooks.domain.errors import (
    InvalidOptionsError,
    NotebookNotFoundError,
    SourceForbiddenError,
)
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.modules.notebooks.wiring_core import NotebooksCore
from app.modules.notebooks.wiring_sources import SourcesServices
from app.shared.actor import Actor
from app.shared.ids import new_id
from tests.factories.notebooks import make_notebook, make_source
from tests.fakes.ai.contracts import make_file
from tests.fakes.notebooks.world import World

import pytest


@pytest.fixture
def workspace(core: NotebooksCore, sources: SourcesServices) -> OpenFlashcardWorkspace:
    """The use case over the test fakes."""
    deps = core.deps
    return OpenFlashcardWorkspace(
        uow_factory=core.uow_factory,
        clock=deps.clock,
        settings=deps.settings,
        rate_limiter=deps.rate_limiter,
        kicker=deps.kicker,
        add_sources=sources.add_sources,
        quota=core.quota,
        limits=deps.effective_limits,
    )


async def _notebook_with_source(
    uow_factory: UowFactory, owner: Actor, *, status: SourceStatus = SourceStatus.READY
) -> tuple[Notebook, UUID]:
    notebook = await make_notebook(uow_factory, owner.user_id)
    source = await make_source(uow_factory, notebook, status=status, title="Mitosis")
    return notebook, source.id


async def test_notebook_sources_are_copied_into_one_hidden_notebook(
    workspace: OpenFlashcardWorkspace,
    uow_factory: UowFactory,
    student: Actor,
) -> None:
    """NB-FC: copies without reading again; hidden from the list; no summary."""
    notebook, source_id = await _notebook_with_source(uow_factory, student)

    first = await workspace.execute(student, [(notebook.id, source_id)], [])
    second = await workspace.execute(student, [(notebook.id, source_id)], [])

    assert first.notebook.id == second.notebook.id
    assert first.notebook.origin is NotebookOrigin.FLASHCARDS
    assert [s.title for s in second.sources] == ["Mitosis"]
    assert second.sources[0].status is SourceStatus.READY
    assert second.notebook.summary_status is SummaryStatus.NONE
    listed = await ListNotebooks(uow_factory=uow_factory).execute(student)
    assert notebook.id in [item.id for item in listed.items]
    assert first.notebook.id not in [item.id for item in listed.items]


async def test_a_file_is_added_through_the_sources_pipeline(
    workspace: OpenFlashcardWorkspace, world: World, student: Actor
) -> None:
    """NB-FC: one of My files becomes a pending source, read in the background."""
    ref = world.files.add_text(make_file(student.user_id, name="a.pdf"), "text")

    result = await workspace.execute(student, [], [ref.id])

    assert [s.status for s in result.sources] == [SourceStatus.PENDING]


async def test_another_students_file_is_refused(
    workspace: OpenFlashcardWorkspace,
    world: World,
    student: Actor,
    other_student: Actor,
) -> None:
    """NB-FC: IDOR, a foreign file."""
    ref = world.files.add_text(make_file(other_student.user_id, name="a.pdf"), "text")

    with pytest.raises(SourceForbiddenError):
        await workspace.execute(student, [], [ref.id])


async def test_another_students_notebook_is_a_404(
    workspace: OpenFlashcardWorkspace,
    uow_factory: UowFactory,
    student: Actor,
    other_student: Actor,
) -> None:
    """NB-FC: IDOR, a foreign notebook; nothing is created for the caller."""
    notebook, source_id = await _notebook_with_source(uow_factory, other_student)

    with pytest.raises(NotebookNotFoundError):
        await workspace.execute(student, [(notebook.id, source_id)], [])


async def test_a_source_of_another_notebook_is_a_404(
    workspace: OpenFlashcardWorkspace,
    uow_factory: UowFactory,
    student: Actor,
    other_student: Actor,
) -> None:
    """NB-FC: IDOR, the caller's notebook id with a foreign source id."""
    mine, _ = await _notebook_with_source(uow_factory, student)
    _, foreign = await _notebook_with_source(uow_factory, other_student)

    with pytest.raises(NotebookNotFoundError):
        await workspace.execute(student, [(mine.id, foreign)], [])


@pytest.mark.parametrize("count", [0, 21])
async def test_the_number_of_sources_is_limited(
    workspace: OpenFlashcardWorkspace, student: Actor, count: int
) -> None:
    """NB-FC: 1 to 20 items."""
    with pytest.raises(InvalidOptionsError):
        await workspace.execute(student, [], [new_id() for _ in range(count)])
