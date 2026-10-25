"""NB-14, NB-17: the assistant's `search_notebook` is hybrid when vectors exist."""

from app.modules.notebooks.application.public_api import NotebooksQueriesImpl
from app.modules.notebooks.domain.passage_hash import passage_hash
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.modules.notebooks.wiring_core import NotebooksCore
from app.shared.actor import Actor
from app.shared.contracts.embeddings import TextToEmbed
from tests.factories.notebooks import make_notebook, make_source
from tests.fakes.vectors.index import make_index

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

TARGET = "Photosynthesis happens inside the leaves of plants."
OTHER = "Governments collect taxes to pay for schools."


async def test_a_question_without_a_matching_word_finds_the_passage_by_meaning(
    uow_factory: UowFactory,
    sessionmaker_in_tx: async_sessionmaker[AsyncSession],
    core: NotebooksCore,
    student: Actor,
) -> None:
    """NB-14: the same call, with an index, returns the passage the words miss."""
    notebook = await make_notebook(uow_factory, student.user_id)
    await make_source(uow_factory, notebook, texts=(TARGET, OTHER))
    index, gateway = make_index(sessionmaker_in_tx)
    await index.ensure([TextToEmbed(passage_hash(t), t) for t in (TARGET, OTHER)])
    lexical = NotebooksQueriesImpl(uow_factory, core.quota)
    hybrid = NotebooksQueriesImpl(uow_factory, core.quota, index)

    by_words = await lexical.search(student.user_id, notebook.id, "synthesis", 5)
    by_both = await hybrid.search(student.user_id, notebook.id, "synthesis", 5)

    assert by_words == []
    assert by_both[0]["text"] == TARGET
    assert ("query", ["synthesis"]) in gateway.calls


async def test_another_students_notebook_is_not_searched_or_embedded_for(
    uow_factory: UowFactory,
    sessionmaker_in_tx: async_sessionmaker[AsyncSession],
    core: NotebooksCore,
    student: Actor,
    other_student: Actor,
) -> None:
    """NB-17: no result and no embedding request for a notebook that is not yours."""
    notebook = await make_notebook(uow_factory, student.user_id)
    await make_source(uow_factory, notebook, texts=(TARGET,))
    index, gateway = make_index(sessionmaker_in_tx)
    hybrid = NotebooksQueriesImpl(uow_factory, core.quota, index)

    found = await hybrid.search(other_student.user_id, notebook.id, "synthesis", 5)

    assert found == []
    assert gateway.calls == []
