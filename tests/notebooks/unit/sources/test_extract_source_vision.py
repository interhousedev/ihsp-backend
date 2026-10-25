"""NB-8: a scanned file is read by the model at once; no text keeps the source."""

from app.modules.notebooks.domain.entities import Notebook, Source
from app.modules.notebooks.domain.enums import SourceFailure, SourceStatus
from app.modules.notebooks.domain.source_input import FileInput
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.modules.notebooks.wiring_sources import SourcesServices
from app.shared.actor import Actor
from tests.fakes.ai.contracts import make_file
from tests.fakes.notebooks.world import World
from tests.fakes.tasks import FakeTaskKicker
from tests.notebooks.unit.sources.support import HookedLlm, add_one, stored

VISION_TASK = "notebooks.extract_source_vision"
PROCESS_TASK = "notebooks.process_source"


async def _scanned(
    sources: SourcesServices,
    world: World,
    uow_factory: UowFactory,
    student: Actor,
    notebook: Notebook,
    pages: int | None = None,
) -> Source:
    """Add a scanned PDF (no text layer); processing hands it to the model."""
    ref = world.files.add(make_file(student.user_id, text_bytes=None, name="scan.pdf"))
    if pages is not None:
        world.files.page_counts[ref.id] = pages
    added = await add_one(sources, student, notebook, FileInput(file_id=ref.id))
    await sources.process_source.execute(added.id)
    handed = await stored(uow_factory, added.id)
    assert handed.status is SourceStatus.PROCESSING
    return handed


async def test_a_scanned_file_is_handed_to_the_model_when_processed(
    sources: SourcesServices,
    world: World,
    uow_factory: UowFactory,
    student: Actor,
    notebook: Notebook,
    kicker: FakeTaskKicker,
) -> None:
    """NB-8: no text found: the model is asked at once, the row shows AI reading."""
    scan = await _scanned(sources, world, uow_factory, student, notebook)

    assert kicker.calls[-1] == (VISION_TASK, {"source_id": str(scan.id)})
    assert "vision_started_at" in scan.ref


async def test_text_found_by_the_model_is_chunked_and_the_source_becomes_ready(
    sources: SourcesServices,
    world: World,
    uow_factory: UowFactory,
    student: Actor,
    notebook: Notebook,
    scripted_llm: HookedLlm,
    kicker: FakeTaskKicker,
) -> None:
    """NB-8: the model's text is stored on the source and goes through processing."""
    scan = await _scanned(sources, world, uow_factory, student, notebook)
    scripted_llm.queue_json({"text": "Cells divide by mitosis."})

    await sources.extract_source_vision.execute(scan.id)
    waiting = await stored(uow_factory, scan.id)
    assert waiting.status is SourceStatus.PENDING
    assert waiting.ref["ai_text"] == "Cells divide by mitosis."
    assert kicker.calls[-1] == (PROCESS_TASK, {"source_id": str(scan.id)})

    await sources.process_source.execute(scan.id)
    done = await stored(uow_factory, scan.id)
    assert done.status is SourceStatus.READY
    assert done.passage_count >= 1
    assert scripted_llm.json_requests[-1]["schema_name"] == "source_text"


async def test_no_text_found_keeps_the_source_ready_without_passages(
    sources: SourcesServices,
    world: World,
    uow_factory: UowFactory,
    student: Actor,
    notebook: Notebook,
    scripted_llm: HookedLlm,
) -> None:
    """NB-8: a blank answer keeps the source ready, with no text."""
    scan = await _scanned(sources, world, uow_factory, student, notebook)
    scripted_llm.queue_json({"text": "   "})

    await sources.extract_source_vision.execute(scan.id)

    kept = await stored(uow_factory, scan.id)
    assert (kept.status, kept.failure) == (SourceStatus.READY, None)
    assert kept.word_count == 0
    assert kept.passage_count == 0


async def test_a_provider_error_fails_the_source_with_provider_error(
    sources: SourcesServices,
    world: World,
    uow_factory: UowFactory,
    student: Actor,
    notebook: Notebook,
    scripted_llm: HookedLlm,
) -> None:
    """NB-8: the model being down ends the read as a failure the user can retry."""
    from app.shared.contracts.ai import AiProviderError

    scan = await _scanned(sources, world, uow_factory, student, notebook)
    for _ in range(3):  # the light model retries twice
        scripted_llm.queue_json(AiProviderError())

    await sources.extract_source_vision.execute(scan.id)

    after = await stored(uow_factory, scan.id)
    assert (after.status, after.failure) == (
        SourceStatus.FAILED,
        SourceFailure.PROVIDER_ERROR,
    )


async def test_a_file_over_the_page_cap_is_not_sent_to_the_model(
    sources: SourcesServices,
    world: World,
    uow_factory: UowFactory,
    student: Actor,
    notebook: Notebook,
    scripted_llm: HookedLlm,
) -> None:
    """NB-8: more than 30 pages are refused before any model call."""
    scan = await _scanned(sources, world, uow_factory, student, notebook, pages=31)

    await sources.extract_source_vision.execute(scan.id)

    after = await stored(uow_factory, scan.id)
    assert (after.status, after.failure) == (
        SourceStatus.FAILED,
        SourceFailure.TOO_LARGE,
    )
    assert scripted_llm.json_requests == []


async def test_reread_of_a_failed_scan_queues_the_model_read(
    sources: SourcesServices,
    world: World,
    uow_factory: UowFactory,
    student: Actor,
    notebook: Notebook,
    kicker: FakeTaskKicker,
) -> None:
    """NB-8: a source failed as no text is read by the model when re-read."""
    scan = await _scanned(sources, world, uow_factory, student, notebook)
    async with uow_factory() as uow:
        locked = await uow.sources.get_for_update(scan.id)
        assert locked is not None
        locked.status = SourceStatus.FAILED
        locked.failure = SourceFailure.NO_TEXT
        await uow.sources.save(locked)
        await uow.commit()

    queued = await sources.reread_source.execute(student, notebook.id, scan.id)

    assert queued.status is SourceStatus.PROCESSING
    assert kicker.calls[-1] == (VISION_TASK, {"source_id": str(scan.id)})
