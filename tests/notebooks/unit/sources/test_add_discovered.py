"""NB-31: pages found by Discover are added as ordinary URL sources."""

from app.modules.notebooks.domain.entities import Notebook
from app.modules.notebooks.domain.enums import SourceKind, SourceStatus
from app.modules.notebooks.domain.errors import (
    SourceDuplicateError,
    SourceUnsupportedError,
)
from app.modules.notebooks.domain.source_input import UrlInput
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.modules.notebooks.wiring_sources import SourcesServices
from app.shared.actor import Actor
from tests.fakes.notebooks.world import World
from tests.notebooks.unit.sources.conftest import Build
from tests.notebooks.unit.sources.support import add_ready

PAGE = "https://school1.example.org/photosynthesis"
TEXT = "Photosynthesis turns light into sugar in the leaves of plants."


async def test_a_discovered_page_becomes_a_url_source_read_by_the_fetcher(
    sources: SourcesServices,
    uow_factory: UowFactory,
    world: World,
    student: Actor,
    notebook: Notebook,
) -> None:
    """NB-31: the title of the result is the source title; the fetcher reads it."""
    world.fetcher.add_page(PAGE, TEXT)

    ready = await add_ready(
        sources,
        uow_factory,
        student,
        notebook,
        UrlInput(url=PAGE, title="Photosynthesis for grade 9"),
    )

    assert ready.kind is SourceKind.URL
    assert ready.title == "Photosynthesis for grade 9"
    assert ready.ref == {"url": PAGE}
    assert ready.status is SourceStatus.READY
    assert world.fetcher.calls == [PAGE]


async def test_a_page_without_a_title_is_named_by_its_host(
    sources: SourcesServices,
    uow_factory: UowFactory,
    world: World,
    student: Actor,
    notebook: Notebook,
) -> None:
    world.fetcher.add_page(PAGE, TEXT)

    ready = await add_ready(sources, uow_factory, student, notebook, UrlInput(url=PAGE))

    assert ready.title == "school1.example.org"


async def test_several_found_pages_are_added_in_one_request(
    sources: SourcesServices, student: Actor, notebook: Notebook
) -> None:
    items = [
        UrlInput(url=f"https://school{n}.example.org/p", title=f"Page {n}")
        for n in (1, 2, 3)
    ]

    result = await sources.add_sources.execute(student, notebook.id, items)

    assert [s.title for s in result.items] == ["Page 1", "Page 2", "Page 3"]
    assert result.rejected == []


async def test_the_same_page_twice_is_a_duplicate(
    sources: SourcesServices, student: Actor, notebook: Notebook
) -> None:
    """ "Already added" in Discover matches the duplicate rule of sources."""
    item = UrlInput(url=PAGE, title="Photosynthesis")
    await sources.add_sources.execute(student, notebook.id, [item])

    again = await sources.add_sources.execute(
        student, notebook.id, [UrlInput(url=PAGE + "#intro", title="Again")]
    )

    assert again.items == []
    assert isinstance(again.rejected[0].error, SourceDuplicateError)


async def test_a_blocked_domain_is_refused_as_a_source(
    build: Build, student: Actor, notebook: Notebook
) -> None:
    """The blocklist of web search also guards URL sources (and subdomains)."""
    sources = build()

    result = await sources.add_sources.execute(
        student,
        notebook.id,
        [
            UrlInput(url="https://www.pornhub.com/view"),
            UrlInput(url="https://de.pornhub.com/view"),
            UrlInput(url="https://notpornhub.com/view"),
        ],
    )

    assert [r.index for r in result.rejected] == [0, 1]
    error = result.rejected[0].error
    assert isinstance(error, SourceUnsupportedError)
    assert error.params == {"hint": "blocked"}
    assert [s.ref["url"] for s in result.items] == ["https://notpornhub.com/view"]
