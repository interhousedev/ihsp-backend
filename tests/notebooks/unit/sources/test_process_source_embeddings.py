"""NB-14: `process_source` asks for passage vectors when it stores a new document."""

from app.modules.notebooks.domain.entities import Notebook
from app.modules.notebooks.domain.source_input import FileInput, TextInput
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.modules.notebooks.wiring_sources import SourcesServices
from app.shared.actor import Actor
from app.shared.wiring import ModuleDeps
from tests.factories.notebooks import make_notebook
from tests.fakes.ai.contracts import make_file
from tests.fakes.notebooks.world import World
from tests.fakes.tasks import FakeTaskKicker
from tests.notebooks.unit.sources.support import add_one, add_ready

EMBED_TASK = "notebooks.embed_passages"
TEXT = "Photosynthesis turns light into chemical energy in plants."


async def test_a_new_document_kicks_the_embedding_job_after_commit(
    sources: SourcesServices,
    uow_factory: UowFactory,
    student: Actor,
    notebook: Notebook,
    kicker: FakeTaskKicker,
) -> None:
    """NB-14: the job gets the id of the document the source now points at."""
    ready = await add_ready(
        sources, uow_factory, student, notebook, TextInput(title="Notes", text=TEXT)
    )

    assert ready.document_id is not None
    assert (EMBED_TASK, {"document_id": str(ready.document_id)}) in kicker.calls


async def test_a_file_known_by_its_checksum_asks_for_nothing(
    sources: SourcesServices,
    uow_factory: UowFactory,
    world: World,
    student: Actor,
    notebook: Notebook,
    kicker: FakeTaskKicker,
) -> None:
    """NB-14: the second notebook reuses the document, so its vectors too."""
    ref = world.files.add_text(make_file(student.user_id), TEXT)
    other = await make_notebook(uow_factory, student.user_id)
    first = await add_one(sources, student, notebook, FileInput(file_id=ref.id))
    await sources.process_source.execute(first.id)
    kicker.calls.clear()

    second = await add_one(sources, student, other, FileInput(file_id=ref.id))
    await sources.process_source.execute(second.id)

    assert EMBED_TASK not in kicker.names()


async def test_nothing_is_kicked_when_vector_search_is_off(
    sources: SourcesServices,
    uow_factory: UowFactory,
    student: Actor,
    notebook: Notebook,
    kicker: FakeTaskKicker,
    module_deps: ModuleDeps,
) -> None:
    """NB-14: FEATURES__VECTOR_SEARCH=false."""
    settings = module_deps.settings
    sources.process_source.settings = settings.model_copy(
        update={
            "features": settings.features.model_copy(update={"vector_search": False})
        }
    )

    await add_ready(
        sources, uow_factory, student, notebook, TextInput(title="Notes", text=TEXT)
    )

    assert EMBED_TASK not in kicker.names()
