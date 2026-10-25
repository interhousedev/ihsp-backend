"""NB-14: full-text search over the passages of a notebook's usable sources."""

from collections.abc import Callable
from typing import Any

from app.modules.notebooks.application.remove_source import RemoveSource
from app.modules.notebooks.application.search_sources import SearchSources
from app.modules.notebooks.domain.entities import Notebook, Source
from app.modules.notebooks.domain.enums import SourceKind, SourceStatus
from app.modules.notebooks.domain.errors import (
    InvalidOptionsError,
    NotebookNotFoundError,
)
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.settings import Settings
from app.shared.actor import Actor
from app.shared.base_error import RateLimitedError
from app.shared.wiring import ModuleDeps
from tests.factories.notebooks import NOW, make_notebook, make_source
from tests.fakes.clock import FixedClock
from tests.notebooks.unit.sources.support import passages_of

import pytest

SearchFactory = Callable[..., SearchSources]
PLANTS = (
    "Photosynthesis happens in the chloroplast of a leaf cell.",
    "Light reactions of photosynthesis split water and release oxygen.",
    "The Calvin cycle uses carbon dioxide to build sugar.",
    "Photosynthesis photosynthesis photosynthesis: the plant makes food.",
)
CELLS = ("Mitochondria release energy for the cell by respiration.",)


@pytest.fixture
def make_search(module_deps: ModuleDeps, uow_factory: UowFactory) -> SearchFactory:
    """Builds the use case, optionally with other limits (the fakes of the module)."""

    def make(*, limits: dict[str, Any] | None = None) -> SearchSources:
        settings: Settings = module_deps.settings
        if limits:
            settings = settings.model_copy(
                update={"limits": settings.limits.model_copy(update=limits)}
            )
        return SearchSources(
            uow_factory=uow_factory,
            settings=settings,
            rate_limiter=module_deps.rate_limiter,
        )

    return make


@pytest.fixture
def search(make_search: SearchFactory) -> SearchSources:
    """The search with the default limits."""
    return make_search()


async def _plants(
    uow_factory: UowFactory, notebook: Notebook, kind: SourceKind = SourceKind.TEXT
) -> Source:
    return await make_source(
        uow_factory, notebook, texts=PLANTS, title="Plants", kind=kind
    )


# - - - Grouping - - -


async def test_hits_are_grouped_by_source_with_title_kind_and_snippet(
    search: SearchSources,
    uow_factory: UowFactory,
    student: Actor,
    notebook: Notebook,
) -> None:
    """NB-14: one entry per source, the passages that match in it."""
    plants = await _plants(uow_factory, notebook, kind=SourceKind.NOTE)
    await make_source(uow_factory, notebook, texts=CELLS, title="Cells")

    result = await search.execute(student, notebook.id, "photosynthesis")

    assert result.query == "photosynthesis"
    assert [s.source_id for s in result.sources] == [plants.id]
    found = result.sources[0]
    assert (found.title, found.kind) == ("Plants", SourceKind.NOTE)
    assert len(found.hits) == 3
    assert all("hotosynthesis" in hit.snippet for hit in found.hits)


async def test_a_hit_names_its_passage(
    search: SearchSources,
    uow_factory: UowFactory,
    student: Actor,
    notebook: Notebook,
) -> None:
    """NB-14: passage id, `seq` and `page` let the viewer open the passage."""
    plants = await _plants(uow_factory, notebook)
    stored = {p.id: p for p in await passages_of(uow_factory, plants.id)}

    result = await search.execute(student, notebook.id, "calvin")

    (hit,) = result.sources[0].hits
    assert hit.passage_id in stored
    assert hit.seq == stored[hit.passage_id].seq == 3
    assert hit.page is None
    assert hit.snippet == PLANTS[2]


async def test_at_most_three_hits_per_source_best_first(
    search: SearchSources,
    uow_factory: UowFactory,
    student: Actor,
    notebook: Notebook,
) -> None:
    """NB-14: a source with four matches shows its three best."""
    await _plants(uow_factory, notebook)

    result = await search.execute(student, notebook.id, "photosynthesis")

    seqs = [hit.seq for hit in result.sources[0].hits]
    assert len(seqs) == 3
    assert seqs[0] == 4  # the passage that repeats the word ranks first


async def test_sources_follow_the_rank_of_their_best_hit(
    search: SearchSources,
    uow_factory: UowFactory,
    student: Actor,
    notebook: Notebook,
) -> None:
    """NB-14: the source whose passage matches best comes first."""
    weak = await make_source(
        uow_factory, notebook, texts=("A note about energy once.",), title="Weak"
    )
    strong = await make_source(
        uow_factory,
        notebook,
        texts=("Energy energy energy: all about energy.",),
        title="Strong",
    )

    result = await search.execute(student, notebook.id, "energy")

    assert [s.source_id for s in result.sources] == [strong.id, weak.id]


async def test_the_limit_caps_the_hits_in_total(
    search: SearchSources,
    uow_factory: UowFactory,
    student: Actor,
    notebook: Notebook,
) -> None:
    """NB-14: `limit` counts hits over all sources."""
    await _plants(uow_factory, notebook)
    await make_source(
        uow_factory,
        notebook,
        texts=("Photosynthesis in algae.", "Photosynthesis in moss."),
        title="Lower plants",
    )

    result = await search.execute(student, notebook.id, "photosynthesis", limit=4)

    assert sum(len(s.hits) for s in result.sources) == 4
    assert len(result.sources) == 2


async def test_a_word_form_of_another_language_ending_still_matches(
    search: SearchSources,
    uow_factory: UowFactory,
    student: Actor,
    notebook: Notebook,
) -> None:
    """NB-14: the lexical search of the assistant: "фотосинтезе" finds "фотосинтез"."""
    source = await make_source(
        uow_factory, notebook, texts=("Фотосинтез идёт на свету.",), title="Биология"
    )

    result = await search.execute(student, notebook.id, "фотосинтезе")

    assert [s.source_id for s in result.sources] == [source.id]
    assert result.sources[0].hits[0].snippet == "Фотосинтез идёт на свету."


# - - - Which sources are searched - - -


async def test_only_ready_and_stale_sources_are_searched(
    search: SearchSources,
    uow_factory: UowFactory,
    student: Actor,
    notebook: Notebook,
) -> None:
    """NB-14: a source that is not usable does not show up, even with passages."""
    ready = await make_source(uow_factory, notebook, texts=("Light one.",))
    stale = await make_source(
        uow_factory, notebook, texts=("Light two.",), status=SourceStatus.STALE
    )
    for status in (SourceStatus.PENDING, SourceStatus.FAILED, SourceStatus.PROCESSING):
        await make_source(
            uow_factory, notebook, texts=(f"Light {status.value}.",), status=status
        )

    result = await search.execute(student, notebook.id, "light")

    assert {s.source_id for s in result.sources} == {ready.id, stale.id}


async def test_a_removed_source_is_not_searched(
    search: SearchSources,
    uow_factory: UowFactory,
    clock: FixedClock,
    student: Actor,
    notebook: Notebook,
) -> None:
    """NB-14: removing a source takes its text out of the search."""
    gone = await make_source(uow_factory, notebook, texts=("Light one.",))
    kept = await make_source(uow_factory, notebook, texts=("Light two.",))
    remove = RemoveSource(uow_factory=uow_factory, clock=clock)
    await remove.execute(student, notebook.id, gone.id)

    result = await search.execute(student, notebook.id, "light")

    assert [s.source_id for s in result.sources] == [kept.id]


async def test_a_deselected_source_is_still_searched(
    search: SearchSources,
    uow_factory: UowFactory,
    student: Actor,
    notebook: Notebook,
) -> None:
    """NB-14: the checkbox picks sources for the chat, not for the search box."""
    source = await make_source(
        uow_factory, notebook, texts=("Light one.",), selected=False
    )

    result = await search.execute(student, notebook.id, "light")

    assert [s.source_id for s in result.sources] == [source.id]


async def test_a_notebook_without_sources_gives_an_empty_result(
    search: SearchSources, student: Actor, notebook: Notebook
) -> None:
    """NB-14: nothing to search, nothing found."""
    result = await search.execute(student, notebook.id, "light")

    assert (result.query, result.sources) == ("light", [])


@pytest.mark.parametrize("query", ["zzzzzz", "что это", "the and"])
async def test_no_match_or_only_stop_words_gives_an_empty_result(
    search: SearchSources,
    uow_factory: UowFactory,
    student: Actor,
    notebook: Notebook,
    query: str,
) -> None:
    """NB-14: an unknown word and a query of stop words find nothing."""
    await _plants(uow_factory, notebook)

    result = await search.execute(student, notebook.id, query)

    assert result.sources == []


# - - - Snippets - - -


async def test_snippets_are_plain_text_without_citation_chips(
    search: SearchSources,
    uow_factory: UowFactory,
    student: Actor,
    notebook: Notebook,
) -> None:
    """NB-14: a saved answer keeps `⟦1⟧` and `⟦w1⟧` in the text, not in the snippet."""
    await make_source(
        uow_factory,
        notebook,
        kind=SourceKind.NOTE,
        texts=("Chlorophyll absorbs light ⟦2⟧ in the leaf ⟦w1,3⟧.\n\nIt is green.",),
        title="Saved answer",
    )

    result = await search.execute(student, notebook.id, "chlorophyll")

    snippet = result.sources[0].hits[0].snippet
    assert snippet == "Chlorophyll absorbs light in the leaf. It is green."
    assert "⟦" not in snippet and "\n" not in snippet


async def test_a_long_passage_is_cut_to_about_200_characters_around_the_match(
    search: SearchSources,
    uow_factory: UowFactory,
    student: Actor,
    notebook: Notebook,
) -> None:
    """NB-14: the snippet is not the whole passage."""
    filler = "Some other words about nothing in particular. " * 30
    await make_source(
        uow_factory,
        notebook,
        texts=(f"{filler}Stomata open at dawn. {filler}",),
        title="Long",
    )

    result = await search.execute(student, notebook.id, "stomata")

    snippet = result.sources[0].hits[0].snippet
    assert "Stomata open at dawn." in snippet
    assert len(snippet) <= 202


# - - - The query - - -


async def test_the_query_is_returned_on_one_line(
    search: SearchSources, student: Actor, notebook: Notebook
) -> None:
    """NB-14: spaces and line breaks in the request are collapsed."""
    result = await search.execute(student, notebook.id, "  light \n  reactions ")

    assert result.query == "light reactions"


@pytest.mark.parametrize("query", ["", " ", "a", "  a  ", "x" * 201])
async def test_a_query_of_less_than_2_or_more_than_200_characters_is_refused(
    search: SearchSources, student: Actor, notebook: Notebook, query: str
) -> None:
    """NB-14: 2 to 200 characters after trimming."""
    with pytest.raises(InvalidOptionsError):
        await search.execute(student, notebook.id, query)


@pytest.mark.parametrize("query", ["ab", "x" * 200])
async def test_a_query_of_2_and_of_200_characters_is_accepted(
    search: SearchSources, student: Actor, notebook: Notebook, query: str
) -> None:
    """NB-14: the limits are inclusive."""
    result = await search.execute(student, notebook.id, query)

    assert result.sources == []


# - - - Access and rate limit - - -


async def test_another_students_notebook_is_not_found(
    search: SearchSources,
    uow_factory: UowFactory,
    student: Actor,
    other_student: Actor,
) -> None:
    """NB-15: searching a foreign notebook is the 404 of a missing one."""
    theirs = await make_notebook(uow_factory, other_student.user_id)
    await make_source(uow_factory, theirs, texts=("Secret light.",))

    with pytest.raises(NotebookNotFoundError):
        await search.execute(student, theirs.id, "light")


async def test_a_deleted_notebook_is_not_found(
    search: SearchSources,
    uow_factory: UowFactory,
    student: Actor,
) -> None:
    """NB-15: a deleted notebook is gone for the search too."""
    notebook = await make_notebook(uow_factory, student.user_id, deleted_at=NOW)

    with pytest.raises(NotebookNotFoundError):
        await search.execute(student, notebook.id, "light")


async def test_only_30_searches_per_minute_and_user(
    search: SearchSources,
    uow_factory: UowFactory,
    student: Actor,
    other_student: Actor,
    notebook: Notebook,
) -> None:
    """NB-14: the 31st search in a minute is a `429`; another user is not affected."""
    theirs = await make_notebook(uow_factory, other_student.user_id)
    for _ in range(30):
        await search.execute(student, notebook.id, "light")

    with pytest.raises(RateLimitedError):
        await search.execute(student, notebook.id, "light")
    result = await search.execute(other_student, theirs.id, "light")

    assert result.sources == []


async def test_the_limit_per_minute_is_a_setting(
    make_search: SearchFactory, student: Actor, notebook: Notebook
) -> None:
    """NB-14: `limits.nb_search_per_minute` changes the cap."""
    search = make_search(limits={"nb_search_per_minute": 2})
    await search.execute(student, notebook.id, "light")
    await search.execute(student, notebook.id, "light")

    with pytest.raises(RateLimitedError):
        await search.execute(student, notebook.id, "light")


async def test_a_refused_query_or_a_foreign_notebook_costs_nothing(
    make_search: SearchFactory,
    uow_factory: UowFactory,
    student: Actor,
    other_student: Actor,
    notebook: Notebook,
) -> None:
    """NB-14: only searches that run count against the minute."""
    search = make_search(limits={"nb_search_per_minute": 1})
    theirs = await make_notebook(uow_factory, other_student.user_id)
    with pytest.raises(InvalidOptionsError):
        await search.execute(student, notebook.id, "a")
    with pytest.raises(NotebookNotFoundError):
        await search.execute(student, theirs.id, "light")

    result = await search.execute(student, notebook.id, "light")

    assert result.sources == []
