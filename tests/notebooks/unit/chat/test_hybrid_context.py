"""NB-6, NB-14: retrieval mode finds passages by meaning when vectors exist."""

from app.modules.ai.domain.errors import AiProviderError
from app.modules.notebooks.application.context_builder import ContextBuilder
from app.modules.notebooks.domain.context import ContextPack
from app.modules.notebooks.domain.entities import Notebook
from app.modules.notebooks.domain.passage_hash import passage_hash
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.settings import Settings
from app.shared.actor import Actor
from app.shared.contracts.embeddings import EmbeddingIndex, TextToEmbed
from app.shared.wiring import ModuleDeps
from tests.factories.notebooks import make_notebook, make_source
from tests.fakes.vectors.index import make_index

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

TARGET = "Photosynthesis happens inside the leaves of plants."
# 30 passages: the question below matches none by word, so only meaning finds TARGET.
TEXTS = tuple(
    TARGET if i == 28 else f"Filler passage number {i} about cells."
    for i in range(1, 31)
)
QUESTION = "synthesis"


@pytest.fixture
def small_context(module_deps: ModuleDeps) -> Settings:
    """Retrieval mode from the first token."""
    base = module_deps.settings
    return base.model_copy(
        update={
            "notebooks": base.notebooks.model_copy(
                update={"chat_full_context_tokens": 10}
            )
        }
    )


@pytest.fixture
async def notebook(uow_factory: UowFactory, student: Actor) -> Notebook:
    """A notebook with one big source."""
    notebook = await make_notebook(uow_factory, student.user_id)
    await make_source(uow_factory, notebook, texts=TEXTS)
    return notebook


async def embed_all(index: EmbeddingIndex) -> None:
    """Give every passage text its vector, as the job does."""
    await index.ensure([TextToEmbed(passage_hash(t), t) for t in TEXTS])


async def pack_for(
    uow_factory: UowFactory,
    notebook: Notebook,
    builder: ContextBuilder,
    question: str = QUESTION,
) -> ContextPack:
    """The chat context for a question."""
    async with uow_factory() as uow:
        sources = await uow.sources.list_for_notebook(notebook.id)
        return await builder.for_chat(
            uow,
            notebook.id,
            sources,
            question=question,
            previous_user_text=None,
            anchor=None,
        )


def texts_of(pack: ContextPack) -> set[str]:
    """The passage texts a pack carries."""
    return {p.text for p in pack.labels.values()}


async def test_without_embeddings_a_question_with_no_matching_word_gets_the_openings(
    uow_factory: UowFactory, notebook: Notebook, small_context: Settings
) -> None:
    """NB-6: today's behaviour: no hit, so the first passages of each source."""
    pack = await pack_for(uow_factory, notebook, ContextBuilder(small_context))

    assert pack.retrieval
    assert TARGET not in texts_of(pack)


async def test_with_embeddings_the_passage_with_the_meaning_is_retrieved(
    uow_factory: UowFactory,
    sessionmaker_in_tx: async_sessionmaker[AsyncSession],
    notebook: Notebook,
    small_context: Settings,
) -> None:
    """NB-14: no shared word, near vector: the passage reaches the model."""
    index, gateway = make_index(sessionmaker_in_tx)
    await embed_all(index)

    pack = await pack_for(uow_factory, notebook, ContextBuilder(small_context, index))

    assert pack.retrieval
    assert TARGET in texts_of(pack)
    assert ("query", [QUESTION]) in gateway.calls  # the question was embedded once


async def test_a_notebook_that_fits_the_context_never_embeds_the_question(
    uow_factory: UowFactory,
    sessionmaker_in_tx: async_sessionmaker[AsyncSession],
    notebook: Notebook,
    module_deps: ModuleDeps,
) -> None:
    """NB-14: full-context mode needs no retrieval and costs nothing."""
    index, gateway = make_index(sessionmaker_in_tx)

    pack = await pack_for(
        uow_factory, notebook, ContextBuilder(module_deps.settings, index)
    )

    assert not pack.retrieval
    assert gateway.calls == []


async def test_switching_the_feature_off_restores_lexical_retrieval(
    uow_factory: UowFactory,
    sessionmaker_in_tx: async_sessionmaker[AsyncSession],
    notebook: Notebook,
    small_context: Settings,
) -> None:
    """NB-14: FEATURES__VECTOR_SEARCH=false: same as having no embeddings."""
    index, gateway = make_index(sessionmaker_in_tx)
    await embed_all(index)
    gateway.calls.clear()
    off = small_context.model_copy(
        update={
            "features": small_context.features.model_copy(
                update={"vector_search": False}
            )
        }
    )

    pack = await pack_for(uow_factory, notebook, ContextBuilder(off, index))

    assert TARGET not in texts_of(pack)
    assert gateway.calls == []


async def test_a_failing_provider_falls_back_to_words(
    uow_factory: UowFactory,
    sessionmaker_in_tx: async_sessionmaker[AsyncSession],
    notebook: Notebook,
    small_context: Settings,
) -> None:
    """NB-14: the chat turn never fails because the embedding provider did."""
    index, gateway = make_index(sessionmaker_in_tx)
    await embed_all(index)
    gateway.error = AiProviderError(support_details="down")

    pack = await pack_for(uow_factory, notebook, ContextBuilder(small_context, index))

    assert pack.retrieval
    assert TARGET not in texts_of(pack)


async def test_hybrid_retrieval_still_finds_what_the_words_find(
    uow_factory: UowFactory,
    sessionmaker_in_tx: async_sessionmaker[AsyncSession],
    notebook: Notebook,
    small_context: Settings,
) -> None:
    """NB-14: a word match is never lost to the vectors."""
    index, _ = make_index(sessionmaker_in_tx)
    await embed_all(index)

    pack = await pack_for(
        uow_factory, notebook, ContextBuilder(small_context, index), "passage number 7"
    )

    assert "Filler passage number 7 about cells." in texts_of(pack)
