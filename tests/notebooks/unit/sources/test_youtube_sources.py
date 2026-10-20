"""URL sources of YouTube videos: captions first, the page as fallback."""

from app.modules.notebooks.domain.entities import Notebook
from app.modules.notebooks.domain.enums import SourceFailure, SourceStatus
from app.modules.notebooks.domain.source_input import UrlInput
from app.modules.notebooks.ports.transcript import (
    TRANSCRIPTS_DISABLED,
    VIDEO_UNAVAILABLE,
)
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.modules.notebooks.wiring_sources import SourcesServices
from app.shared.actor import Actor
from tests.fakes.notebooks.world import World
from tests.notebooks.unit.sources.support import add_ready, passages_of

import pytest

ID = "dQw4w9WgXcQ"
URL = f"https://youtu.be/{ID}"
PAGE = "A video page with a long description about photosynthesis in leaves."
LINES = [(0.0, "Plants turn light into sugar."), (7.5, "Chlorophyll absorbs it.")]


async def test_a_video_is_read_from_its_captions_in_preferred_order(
    sources: SourcesServices,
    uow_factory: UowFactory,
    world: World,
    student: Actor,
    notebook: Notebook,
) -> None:
    """The captions are the text; the page is not fetched; uz, ru, en are preferred."""
    world.transcripts.add_video(ID, LINES)
    world.fetcher.add_page(URL, PAGE)

    ready = await add_ready(sources, uow_factory, student, notebook, UrlInput(url=URL))

    assert ready.status is SourceStatus.READY
    assert world.transcripts.calls == [(ID, ("uz", "ru", "en"))]
    assert world.fetcher.calls == []
    text = " ".join(p.text for p in await passages_of(uow_factory, ready.id))
    assert "[0:00] Plants turn light into sugar." in text
    assert "[0:07] Chlorophyll absorbs it." in text


async def test_a_video_without_captions_falls_back_to_the_page(
    sources: SourcesServices,
    uow_factory: UowFactory,
    world: World,
    student: Actor,
    notebook: Notebook,
) -> None:
    """Disabled captions and a page with text: the source is read from the page."""
    world.transcripts.fail(ID, TRANSCRIPTS_DISABLED)
    world.fetcher.add_page(URL, PAGE)

    ready = await add_ready(sources, uow_factory, student, notebook, UrlInput(url=URL))

    assert ready.status is SourceStatus.READY
    assert world.fetcher.calls == [URL]


@pytest.mark.parametrize("code", ["no_transcript", TRANSCRIPTS_DISABLED])
async def test_no_captions_and_no_page_text_is_no_transcript(
    sources: SourcesServices,
    uow_factory: UowFactory,
    world: World,
    student: Actor,
    notebook: Notebook,
    code: str,
) -> None:
    """A clear failure: the video has no transcript and the page has no text."""
    world.transcripts.fail(ID, code)

    failed = await add_ready(sources, uow_factory, student, notebook, UrlInput(url=URL))

    assert failed.status is SourceStatus.FAILED
    assert failed.failure is SourceFailure.NO_TRANSCRIPT


async def test_a_provider_fault_without_a_page_is_the_page_failure(
    sources: SourcesServices,
    uow_factory: UowFactory,
    world: World,
    student: Actor,
    notebook: Notebook,
) -> None:
    """Video unavailable and the page cannot be fetched: the page's failure is kept."""
    world.transcripts.fail(ID, VIDEO_UNAVAILABLE)

    failed = await add_ready(sources, uow_factory, student, notebook, UrlInput(url=URL))

    assert failed.status is SourceStatus.FAILED
    assert failed.failure is SourceFailure.FETCH_FAILED
