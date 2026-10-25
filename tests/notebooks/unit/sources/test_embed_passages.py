"""NB-14: `notebooks.embed_passages` embeds each distinct passage text once."""

from app.modules.ai.infrastructure.fake_embeddings import FakeEmbeddingGateway
from app.modules.notebooks.application.embed_passages import EmbedPassages
from app.modules.notebooks.domain.entities import Notebook
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.settings import Settings
from app.shared.actor import Actor
from app.shared.contracts.embeddings import EmbeddingIndex
from app.shared.wiring import ModuleDeps
from tests.factories.notebooks import make_notebook, make_source
from tests.fakes.vectors.index import make_index
from tests.fakes.vectors.stores import FakeTokenBudget

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

SUGAR = "Plants make sugar from light in the leaves."
CAT = "The cat sat on the warm windowsill all afternoon."
TAXES = "Governments collect taxes to pay for schools."


def job(
    uow_factory: UowFactory,
    index: EmbeddingIndex | None,
    settings: Settings,
    **vectors: int,
) -> EmbedPassages:
    """The job over the test transaction, with other `VECTORS__*` values."""
    changed = settings.model_copy(
        update={"vectors": settings.vectors.model_copy(update=vectors)}
    )
    return EmbedPassages(uow_factory=uow_factory, embeddings=index, settings=changed)


@pytest.fixture
async def notebook(uow_factory: UowFactory, student: Actor) -> Notebook:
    """A stored notebook of the student."""
    return await make_notebook(uow_factory, student.user_id)


@pytest.fixture
def settings_of(module_deps: ModuleDeps) -> Settings:
    """The settings the module runs with."""
    return module_deps.settings


async def test_a_text_shared_by_two_documents_is_embedded_once(
    uow_factory: UowFactory,
    sessionmaker_in_tx: async_sessionmaker[AsyncSession],
    notebook: Notebook,
    settings_of: Settings,
) -> None:
    """NB-14: documents differ, the passage text is one: one vector, one payment."""
    await make_source(uow_factory, notebook, texts=(SUGAR, CAT))
    await make_source(uow_factory, notebook, texts=(CAT, TAXES))
    index, gateway = make_index(sessionmaker_in_tx)

    done = await job(uow_factory, index, settings_of).execute()

    assert done["embedded"] == 3
    assert sorted(gateway.texts) == sorted([SUGAR, CAT, TAXES])
    assert done["tokens"] > 0


async def test_a_second_run_finds_nothing_to_do(
    uow_factory: UowFactory,
    sessionmaker_in_tx: async_sessionmaker[AsyncSession],
    notebook: Notebook,
    settings_of: Settings,
) -> None:
    """NB-14: the backfill job is cheap when everything has its vector."""
    await make_source(uow_factory, notebook, texts=(SUGAR, CAT))
    index, gateway = make_index(sessionmaker_in_tx)
    use_case = job(uow_factory, index, settings_of)
    await use_case.execute()
    gateway.calls.clear()

    again = await use_case.execute()

    assert again["embedded"] == 0
    assert gateway.calls == []


async def test_the_document_job_embeds_that_document_only(
    uow_factory: UowFactory,
    sessionmaker_in_tx: async_sessionmaker[AsyncSession],
    notebook: Notebook,
    settings_of: Settings,
) -> None:
    """NB-14: the kick after `process_source` carries the new document's id."""
    mine = await make_source(uow_factory, notebook, texts=(SUGAR, CAT))
    await make_source(uow_factory, notebook, texts=(TAXES,))
    index, gateway = make_index(sessionmaker_in_tx)
    assert mine.document_id is not None

    await job(uow_factory, index, settings_of).execute(mine.document_id)

    assert sorted(gateway.texts) == sorted([SUGAR, CAT])


async def test_a_big_document_is_embedded_in_rounds_until_nothing_is_missing(
    uow_factory: UowFactory,
    sessionmaker_in_tx: async_sessionmaker[AsyncSession],
    notebook: Notebook,
    settings_of: Settings,
) -> None:
    """NB-14: 5 passages, 2 per run: the document job loops, the cron would not."""
    texts = tuple(f"Passage number {n} about sugar." for n in range(5))
    source = await make_source(uow_factory, notebook, texts=texts)
    index, gateway = make_index(sessionmaker_in_tx)
    assert source.document_id is not None

    done = await job(uow_factory, index, settings_of, backfill_texts_per_run=2).execute(
        source.document_id
    )

    assert done["embedded"] == 5
    assert sorted(gateway.texts) == sorted(texts)


async def test_the_backfill_takes_one_capped_slice_per_run(
    uow_factory: UowFactory,
    sessionmaker_in_tx: async_sessionmaker[AsyncSession],
    notebook: Notebook,
    settings_of: Settings,
) -> None:
    """NB-14: bounded work per cron run; the next run continues."""
    texts = tuple(f"Passage number {n} about sugar." for n in range(5))
    await make_source(uow_factory, notebook, texts=texts)
    index, gateway = make_index(sessionmaker_in_tx)
    use_case = job(uow_factory, index, settings_of, backfill_texts_per_run=2)

    first = await use_case.execute()
    second = await use_case.execute()
    third = await use_case.execute()
    fourth = await use_case.execute()

    assert [first["embedded"], second["embedded"], third["embedded"]] == [2, 2, 1]
    assert fourth["embedded"] == 0
    assert sorted(gateway.texts) == sorted(texts)


async def test_the_daily_token_budget_defers_the_rest(
    uow_factory: UowFactory,
    sessionmaker_in_tx: async_sessionmaker[AsyncSession],
    notebook: Notebook,
    settings_of: Settings,
) -> None:
    """NB-14: cheap but bounded: no more batches once the budget is spent."""
    texts = tuple(f"Passage number {n} about sugar." for n in range(6))
    source = await make_source(uow_factory, notebook, texts=texts)
    gateway = FakeEmbeddingGateway(batch_size=2)
    index, _ = make_index(
        sessionmaker_in_tx, gateway=gateway, budget=FakeTokenBudget(limit=1)
    )
    assert source.document_id is not None

    done = await job(uow_factory, index, settings_of).execute(source.document_id)

    assert done["embedded"] == 2 and done["deferred"] == 4
    assert len(gateway.calls) == 1


async def test_nothing_is_embedded_when_vector_search_is_switched_off(
    uow_factory: UowFactory,
    sessionmaker_in_tx: async_sessionmaker[AsyncSession],
    notebook: Notebook,
    settings_of: Settings,
) -> None:
    """NB-14: FEATURES__VECTOR_SEARCH=false: no request, no cost."""
    await make_source(uow_factory, notebook, texts=(SUGAR,))
    index, gateway = make_index(sessionmaker_in_tx)
    off = settings_of.model_copy(
        update={
            "features": settings_of.features.model_copy(update={"vector_search": False})
        }
    )

    done = await EmbedPassages(
        uow_factory=uow_factory, embeddings=index, settings=off
    ).execute()

    assert done["embedded"] == 0 and gateway.calls == []


async def test_without_an_index_the_job_does_nothing(
    uow_factory: UowFactory, notebook: Notebook, settings_of: Settings
) -> None:
    """NB-14: a process built without the vectors module."""
    await make_source(uow_factory, notebook, texts=(SUGAR,))

    done = await job(uow_factory, None, settings_of).execute()

    assert done == {"embedded": 0, "deferred": 0, "tokens": 0, "cost_micro": 0}


async def test_a_provider_failure_propagates_so_the_task_is_retried(
    uow_factory: UowFactory,
    sessionmaker_in_tx: async_sessionmaker[AsyncSession],
    notebook: Notebook,
    settings_of: Settings,
) -> None:
    """NB-14: taskiq retries; the cron run would also pick the texts up."""
    await make_source(uow_factory, notebook, texts=(SUGAR,))
    index, gateway = make_index(sessionmaker_in_tx)
    gateway.error = RuntimeError("provider down")

    with pytest.raises(RuntimeError):
        await job(uow_factory, index, settings_of).execute()
