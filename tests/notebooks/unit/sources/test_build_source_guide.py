"""NB-4: `notebooks.build_source_guide` writes the guide of a ready source."""

from typing import Any
from uuid import UUID

from app.modules.notebooks.domain.entities import Notebook, SourceGuide
from app.modules.notebooks.domain.enums import GuideStatus, SourceStatus
from app.modules.notebooks.domain.language import language_name
from app.modules.notebooks.domain.source_input import NoteInput
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.modules.notebooks.wiring_core import NotebooksCore
from app.modules.notebooks.wiring_sources import SourcesServices
from app.shared.actor import Actor
from app.shared.ai_tasks import AiTask
from app.shared.contracts.ai import AiInvalidOutputError, AiProviderError
from app.shared.ids import new_id
from tests.factories.notebooks import make_source
from tests.fakes.tasks import FakeTaskKicker
from tests.notebooks.unit.sources.conftest import Build
from tests.notebooks.unit.sources.support import (
    GUIDE,
    GUIDE_TASK,
    HookedLlm,
    add_ready,
    stored,
)

import pytest

TEXTS = (
    "Photosynthesis turns light into chemical energy in plants.",
    "It happens in the chloroplasts, which contain chlorophyll.",
)
EXPECTED = SourceGuide(
    summary=GUIDE["summary"],
    key_topics=GUIDE["key_topics"],
    questions=GUIDE["questions"],
)
WEIGHTED = 200  # the scripted usage: 100 input + 5 x 20 output


async def _used(core: NotebooksCore, actor: Actor) -> int:
    return (await core.budget.usage(actor.user_id)).session.used


async def _source(uow_factory: UowFactory, notebook: Notebook, **fields: Any) -> UUID:
    source = await make_source(
        uow_factory, notebook, title="Biology 10", texts=TEXTS, **fields
    )
    return source.id


# - - - Building - - -


async def test_the_guide_is_asked_from_the_light_model_and_stored(
    sources: SourcesServices,
    uow_factory: UowFactory,
    core: NotebooksCore,
    scripted_llm: HookedLlm,
    student: Actor,
    notebook: Notebook,
) -> None:
    """NB-4: the model reads the title and the text; the guide and the budget follow."""
    source_id = await _source(uow_factory, notebook)
    scripted_llm.queue_json(GUIDE)

    await sources.build_source_guide.execute(source_id)

    saved = await stored(uow_factory, source_id)
    assert saved.guide == EXPECTED
    assert saved.guide_status is GuideStatus.READY
    assert saved.status is SourceStatus.READY
    (request,) = scripted_llm.json_requests
    assert request["schema_name"] == "nb_guide"
    assert request["model"] == core.llm.model(AiTask.SOURCE_GUIDE)
    assert request["max_tokens"] == 800
    message = request["messages"][0]["content"]
    assert message.startswith('<source title="Biology 10">')
    assert all(text in message for text in TEXTS)
    assert await _used(core, student) == WEIGHTED


@pytest.mark.parametrize(
    ("user_locale", "language"), [("en", "en"), ("ru", "ru"), ("uz", "uz")]
)
async def test_the_guide_is_written_in_the_students_language(
    sources: SourcesServices,
    uow_factory: UowFactory,
    scripted_llm: HookedLlm,
    notebook: Notebook,
    language: str,
) -> None:
    """NB-4: the language of the locale, not the language of the source."""
    source_id = await _source(uow_factory, notebook)
    scripted_llm.queue_json(GUIDE)

    await sources.build_source_guide.execute(source_id)

    assert language_name(language) in scripted_llm.json_requests[0]["system"]


async def test_a_stale_source_gets_a_guide_too(
    sources: SourcesServices,
    uow_factory: UowFactory,
    scripted_llm: HookedLlm,
    notebook: Notebook,
) -> None:
    """NB-4: outdated text is still usable text."""
    source_id = await _source(uow_factory, notebook, status=SourceStatus.STALE)
    scripted_llm.queue_json(GUIDE)

    await sources.build_source_guide.execute(source_id)

    assert (await stored(uow_factory, source_id)).guide == EXPECTED


async def test_a_long_source_is_sampled_evenly(
    sources: SourcesServices,
    uow_factory: UowFactory,
    scripted_llm: HookedLlm,
    notebook: Notebook,
) -> None:
    """NB-4: about 30 000 tokens reach the model, starting with the first passage."""
    texts = tuple(f"p{n:03d} " + "word " * 120 for n in range(200))
    source = await make_source(uow_factory, notebook, title="Long", texts=texts)
    scripted_llm.queue_json(GUIDE)

    await sources.build_source_guide.execute(source.id)

    message = scripted_llm.json_requests[0]["messages"][0]["content"]
    assert "p000 " in message
    assert "p199 " not in message
    assert len(message) < sum(len(t) for t in texts) * 0.8


async def test_a_pasted_text_goes_through_the_whole_pipeline_with_the_fake_model(
    sources: SourcesServices,
    uow_factory: UowFactory,
    student: Actor,
    notebook: Notebook,
    kicker: FakeTaskKicker,
) -> None:
    """NB-4: the deterministic fake model answers the real prompts validly."""
    ready = await add_ready(
        sources,
        uow_factory,
        student,
        notebook,
        NoteInput(title="Cells", body_md="\n\n".join(TEXTS)),
    )
    assert (GUIDE_TASK, {"source_id": str(ready.id)}) in kicker.calls

    await sources.build_source_guide.execute(ready.id)

    saved = await stored(uow_factory, ready.id)
    assert saved.guide_status is GuideStatus.READY
    assert saved.guide is not None and saved.guide.summary


# - - - Retries and failures - - -


@pytest.mark.parametrize(("errors", "pauses"), [(1, [2.0]), (2, [2.0, 4.0])])
async def test_provider_errors_are_retried_with_a_growing_pause(
    sources: SourcesServices,
    uow_factory: UowFactory,
    core: NotebooksCore,
    scripted_llm: HookedLlm,
    student: Actor,
    notebook: Notebook,
    sleeps: list[float],
    errors: int,
    pauses: list[float],
) -> None:
    """NB-4: up to two retries; only the successful call is counted in the budget."""
    source_id = await _source(uow_factory, notebook)
    for _ in range(errors):
        scripted_llm.queue_error(AiProviderError())
    scripted_llm.queue_json(GUIDE)

    await sources.build_source_guide.execute(source_id)

    assert (await stored(uow_factory, source_id)).guide == EXPECTED
    assert scripted_llm.calls == errors + 1
    assert sleeps == pauses
    assert await _used(core, student) == WEIGHTED


async def test_when_every_try_fails_the_guide_fails_but_not_the_source(
    sources: SourcesServices,
    uow_factory: UowFactory,
    core: NotebooksCore,
    scripted_llm: HookedLlm,
    student: Actor,
    notebook: Notebook,
    sleeps: list[float],
) -> None:
    """NB-4: three provider errors end in `failed`; the text stays usable."""
    source_id = await _source(uow_factory, notebook)
    for _ in range(3):
        scripted_llm.queue_error(AiProviderError())

    await sources.build_source_guide.execute(source_id)

    saved = await stored(uow_factory, source_id)
    assert (saved.guide, saved.guide_status) == (None, GuideStatus.FAILED)
    assert (saved.status, saved.failure) == (SourceStatus.READY, None)
    assert scripted_llm.calls == 3
    assert sleeps == [2.0, 4.0]
    assert await _used(core, student) == 0


@pytest.mark.parametrize(
    "answer",
    [{"summary": "  ", "key_topics": [], "questions": []}, AiInvalidOutputError()],
)
async def test_an_invalid_answer_fails_the_guide_without_retries(
    sources: SourcesServices,
    uow_factory: UowFactory,
    scripted_llm: HookedLlm,
    notebook: Notebook,
    sleeps: list[float],
    answer: dict[str, Any] | Exception,
) -> None:
    """NB-4: a document without a summary, or a non-JSON answer, is not retried."""
    source_id = await _source(uow_factory, notebook)
    scripted_llm.queue_json(answer)

    await sources.build_source_guide.execute(source_id)

    assert (await stored(uow_factory, source_id)).guide_status is GuideStatus.FAILED
    assert scripted_llm.calls == 1
    assert sleeps == []


async def test_an_empty_budget_fails_the_guide_without_calling_the_model(
    build: Build,
    uow_factory: UowFactory,
    scripted_llm: HookedLlm,
    notebook: Notebook,
) -> None:
    """NB-14, NB-4: the guide is the first thing a student loses at a limit."""
    sources = build(limits={"nb_session_tokens_student": 10})
    source_id = await _source(uow_factory, notebook)

    await sources.build_source_guide.execute(source_id)

    assert (await stored(uow_factory, source_id)).guide_status is GuideStatus.FAILED
    assert scripted_llm.calls == 0


# - - - When nothing is built - - -


@pytest.mark.parametrize(
    "status",
    [
        SourceStatus.PENDING,
        SourceStatus.PROCESSING,
        SourceStatus.FAILED,
        SourceStatus.UNAVAILABLE,
    ],
)
async def test_sources_without_usable_text_get_no_guide(
    sources: SourcesServices,
    uow_factory: UowFactory,
    scripted_llm: HookedLlm,
    notebook: Notebook,
    status: SourceStatus,
) -> None:
    """NB-4: only ready and stale sources are summarised."""
    source_id = await _source(uow_factory, notebook, status=status)

    await sources.build_source_guide.execute(source_id)

    assert (await stored(uow_factory, source_id)).guide_status is GuideStatus.NONE
    assert scripted_llm.calls == 0


async def test_an_existing_guide_is_not_built_again(
    sources: SourcesServices,
    uow_factory: UowFactory,
    scripted_llm: HookedLlm,
    notebook: Notebook,
) -> None:
    """NB-4: a repeated job costs nothing."""
    source_id = await _source(
        uow_factory, notebook, guide=EXPECTED, guide_status=GuideStatus.READY
    )

    await sources.build_source_guide.execute(source_id)

    assert scripted_llm.calls == 0


async def test_a_source_without_passages_and_an_unknown_source_are_skipped(
    sources: SourcesServices,
    uow_factory: UowFactory,
    scripted_llm: HookedLlm,
    notebook: Notebook,
) -> None:
    """NB-4: nothing to read, nothing to ask."""
    empty = await make_source(uow_factory, notebook, texts=())

    await sources.build_source_guide.execute(empty.id)
    await sources.build_source_guide.execute(new_id())

    assert scripted_llm.calls == 0
    assert (await stored(uow_factory, empty.id)).guide_status is GuideStatus.NONE


async def test_a_guide_for_text_that_changed_meanwhile_is_dropped(
    sources: SourcesServices,
    uow_factory: UowFactory,
    scripted_llm: HookedLlm,
    student: Actor,
    notebook: Notebook,
) -> None:
    """NB-4: the model answers about the old text; the new run builds its own guide."""
    note = await add_ready(
        sources,
        uow_factory,
        student,
        notebook,
        NoteInput(title="Cells", body_md=TEXTS[0]),
    )

    async def edit_while_the_model_works() -> None:
        scripted_llm.before_json = None
        await sources.update_source.execute(
            student, notebook.id, note.id, {"body_md": TEXTS[1]}
        )
        await sources.process_source.execute(note.id)

    scripted_llm.before_json = edit_while_the_model_works
    scripted_llm.queue_json(GUIDE)

    await sources.build_source_guide.execute(note.id)

    reprocessed = await stored(uow_factory, note.id)
    assert reprocessed.guide is None
    assert reprocessed.guide_status is GuideStatus.NONE
    assert reprocessed.content_hash != note.content_hash

    scripted_llm.queue_json({**GUIDE, "summary": "Chlorophyll is green."})
    await sources.build_source_guide.execute(note.id)

    assert (await stored(uow_factory, note.id)).guide_status is GuideStatus.READY
