"""Task 4.1: the platform database is searched before the web."""

from app.modules.ai.application.web_search import WebSearchService
from app.modules.ai.domain.db_first import density, judge, query_terms
from app.settings import Settings
from app.shared.actor import Actor, Role
from app.shared.contracts.web_search import PlatformPassage
from tests.factories import make_actor
from tests.fakes.ai.stores import InMemorySearchQuotaStore
from tests.fakes.ai.web_search import ScriptedJson, ScriptedWebSearch
from tests.fakes.clock import FixedClock

QUERY = "photosynthesis chlorophyll light"


class FakePlatform:
    """Returns the given passages."""

    def __init__(self, passages: list[PlatformPassage]) -> None:
        """Store them."""
        self.passages = passages

    async def search(
        self, actor: Actor, query: str, limit: int
    ) -> list[PlatformPassage]:
        """Return the stored passages."""
        return self.passages


def dense(n: int) -> PlatformPassage:
    """A passage that is about the query."""
    return PlatformPassage(
        f"Book {n}",
        f"/library/{n}",
        "Photosynthesis uses chlorophyll and light to make sugar. " * 2,
    )


def diluted() -> PlatformPassage:
    """100 on-topic tokens inside 10,000 others."""
    text = "photosynthesis " * 100 + "filler " * 9900
    return PlatformPassage("Huge site", "/library/huge", text)


def rig(passages: list[PlatformPassage]) -> tuple[WebSearchService, ScriptedWebSearch]:
    """The service over a fake platform and a scripted web."""
    web = ScriptedWebSearch()
    service = WebSearchService(
        store=InMemorySearchQuotaStore(),
        gateway=web,
        llm=ScriptedJson(),  # type: ignore[arg-type]
        clock=FixedClock(),
        settings=Settings(),
        platform=FakePlatform(passages),
    )
    return service, web


def test_density_of_a_diluted_page_is_tiny() -> None:
    """100 on-topic tokens in 10,000 give 0.01."""
    assert density(diluted().text, query_terms("photosynthesis")) == 0.01


async def test_low_density_site_runs_the_web_search() -> None:
    """A diluted page is not dense, so the web is searched."""
    service, web = rig([diluted()])
    out = await service.search(make_actor(Role.STUDENT), query=QUERY, locale="en")
    assert len(web.calls) == 1
    assert not out.web_skipped
    assert all(h.origin == "web" for h in out.hits)


async def test_three_dense_passages_skip_the_web() -> None:
    """Coverage and count are enough: no web call, hits marked from the database."""
    service, web = rig([dense(1), dense(2), dense(3)])
    out = await service.search(make_actor(Role.STUDENT), query=QUERY, locale="en")
    assert web.calls == []
    assert out.web_skipped
    assert out.quota.used == 0
    assert [h.origin for h in out.hits] == ["db"] * 3


async def test_mixed_results_search_the_web_and_keep_good_db_hits() -> None:
    """Two dense passages and a diluted one: web runs, only dense ones are kept."""
    service, web = rig([dense(1), diluted(), dense(2)])
    out = await service.search(make_actor(Role.STUDENT), query=QUERY, locale="en")
    assert len(web.calls) == 1
    origins = [h.origin for h in out.hits]
    assert origins[:2] == ["db", "db"]
    assert origins[2:] and set(origins[2:]) == {"web"}


def test_thresholds_come_from_settings_and_default() -> None:
    """Defaults are 0.7 and 3; env names are IHSP_WEB_SEARCH__DB_FIRST__*."""
    cfg = Settings().web_search.db_first
    assert (cfg.min_coverage, cfg.min_passages) == (0.7, 3)


def test_judge_respects_the_thresholds() -> None:
    """Raising min_passages turns a sufficient result into an insufficient one."""
    passages = [dense(1), dense(2), dense(3)]
    ok = judge(passages, QUERY, min_density=0.2, min_coverage=0.7, min_passages=3)
    no = judge(passages, QUERY, min_density=0.2, min_coverage=0.7, min_passages=4)
    assert ok.sufficient and not no.sufficient


async def test_composite_merges_and_dedupes_with_references() -> None:
    """Two searches with the same library passage give it once, with its reference."""
    from app.modules.ai.infrastructure.notebook_platform_search import (
        CompositePlatformSearch,
    )

    lib = PlatformPassage(
        "Book", "/library/b", "Photosynthesis text", ref_kind="library_item", ref_id="1"
    )
    other = PlatformPassage("Nb", "/n", "Chlorophyll text", ref_kind="notebook_source")
    both = CompositePlatformSearch([FakePlatform([lib, other]), FakePlatform([lib])])
    found = await both.search(make_actor(Role.STUDENT), "x", 5)
    assert [p.ref_kind for p in found] == ["library_item", "notebook_source"]


async def test_db_hits_carry_the_reference() -> None:
    """A dense library hit reaches Discover with its kind and id."""
    p = PlatformPassage("B", "/l", dense(1).text, ref_kind="library_item", ref_id="abc")
    service, _ = rig([p, dense(2), dense(3)])
    out = await service.search(make_actor(Role.STUDENT), query=QUERY, locale="en")
    assert (out.hits[0].ref_kind, out.hits[0].ref_id) == ("library_item", "abc")
