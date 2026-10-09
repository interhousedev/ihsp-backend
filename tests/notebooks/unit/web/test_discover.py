"""NB-31: Discover sources, the web search of a notebook (fast and deep)."""

from app.modules.notebooks.application.discover_sources import DiscoverSources
from app.modules.notebooks.domain.entities import AutoSettings
from app.modules.notebooks.domain.enums import NotebookOrigin, SourceKind
from app.modules.notebooks.domain.errors import (
    AutoNotebookReadOnlyError,
    InvalidOptionsError,
    NotebookNotFoundError,
)
from app.shared.actor import Actor
from app.shared.contracts.web_search import (
    SearchReply,
    WebSearchDisabledError,
    WebSearchQuotaError,
    WebSearchUnavailableError,
)
from app.shared.ids import new_id
from tests.factories.notebooks import make_notebook, make_source
from tests.fakes.ai.web_search import page
from tests.notebooks.unit.web.conftest import WebCore

import pytest


async def test_a_fast_discover_lists_pages_with_reasons_and_the_quota(
    make_web_core: WebCore, student: Actor
) -> None:
    """NB-31: title, URL, site, snippet and why; "9 of 10 left"."""
    core, web = make_web_core()
    notebook = await make_notebook(core.uow_factory, student.user_id)

    view = await DiscoverSources(core).execute(
        student, notebook.id, "  photosynthesis  for grade 9 ", "fast"
    )

    assert view.mode == "fast"
    assert view.queries == ("photosynthesis for grade 9",)
    first = view.results[0]
    assert first.hit.url == "https://school1.example.org/photosynthesis"
    assert first.hit.why == "It explains the topic."
    assert first.already_added is False
    assert (view.quota.used, view.quota.remaining) == (1, 9)
    assert web.search.calls[0].explain is True


async def test_a_deep_discover_searches_several_times_and_costs_three(
    make_web_core: WebCore, student: Actor
) -> None:
    core, web = make_web_core()
    notebook = await make_notebook(core.uow_factory, student.user_id)
    web.json.push(
        {"queries": ["a", "b"]},
        {"results": [{"index": 3, "why": "Best."}, {"index": 0, "why": "Next."}]},
    )

    view = await DiscoverSources(core).execute(student, notebook.id, "topic", "deep")

    assert view.mode == "deep"
    assert view.queries == ("topic", "a", "b")
    assert [p.hit.why for p in view.results] == ["Best.", "Next."]
    assert view.results[0].hit.site == "school4.example.org"
    assert view.quota.used == 3


async def test_a_page_the_notebook_already_has_is_marked(
    make_web_core: WebCore, student: Actor
) -> None:
    """NB-31: "Already added" is disabled in the list."""
    core, web = make_web_core()
    notebook = await make_notebook(core.uow_factory, student.user_id)
    known = "https://school2.example.org/photosynthesis"
    await make_source(
        core.uow_factory,
        notebook,
        kind=SourceKind.URL,
        ref={"url": known},
        ref_key=f"url:{known}",
    )

    view = await DiscoverSources(core).execute(student, notebook.id, "topic")

    assert [p.already_added for p in view.results] == [False, True, False]


async def test_an_empty_result_is_a_normal_answer(
    make_web_core: WebCore, student: Actor
) -> None:
    core, web = make_web_core()
    notebook = await make_notebook(core.uow_factory, student.user_id)
    web.search.push(SearchReply(hits=(), usage={}))

    view = await DiscoverSources(core).execute(student, notebook.id, "zzzzzz")

    assert view.results == []
    assert view.quota.used == 1


async def test_the_pages_are_not_fetched_or_stored_by_discover(
    make_web_core: WebCore, student: Actor
) -> None:
    core, _ = make_web_core()
    notebook = await make_notebook(core.uow_factory, student.user_id)

    await DiscoverSources(core).execute(student, notebook.id, "topic")

    async with core.uow_factory() as uow:
        assert await uow.sources.list_for_notebook(notebook.id) == []


# - - - refusals - - -


async def test_when_the_searches_are_used_up_discover_is_refused(
    make_web_core: WebCore, student: Actor
) -> None:
    """NB-33: 429 web-search/quota-exceeded."""
    core, web = make_web_core(limits={"web_search_per_day_student": 2})
    notebook = await make_notebook(core.uow_factory, student.user_id)
    discover = DiscoverSources(core)
    await discover.execute(student, notebook.id, "one")

    with pytest.raises(WebSearchQuotaError) as caught:
        await discover.execute(student, notebook.id, "two", "deep")  # costs 3

    assert caught.value.params["needed"] == 3
    assert (await web.service.quota(student)).used == 1


async def test_with_the_feature_off_discover_answers_disabled(
    make_web_core: WebCore, student: Actor
) -> None:
    """NB-32: FEATURES__WEB_SEARCH=false."""
    core, web = make_web_core(features={"web_search": False})
    notebook = await make_notebook(core.uow_factory, student.user_id)

    with pytest.raises(WebSearchDisabledError):
        await DiscoverSources(core).execute(student, notebook.id, "topic")

    assert web.search.calls == []


async def test_without_a_search_service_discover_is_disabled(
    make_web_core: WebCore, student: Actor
) -> None:
    core, _ = make_web_core(with_search=False)
    notebook = await make_notebook(core.uow_factory, student.user_id)

    with pytest.raises(WebSearchDisabledError):
        await DiscoverSources(core).execute(student, notebook.id, "topic")


async def test_a_provider_failure_costs_nothing(
    make_web_core: WebCore, student: Actor
) -> None:
    core, web = make_web_core()
    notebook = await make_notebook(core.uow_factory, student.user_id)
    web.search.fail_next()

    with pytest.raises(WebSearchUnavailableError):
        await DiscoverSources(core).execute(student, notebook.id, "topic")

    assert (await web.service.quota(student)).used == 0


async def test_another_students_notebook_is_not_found_and_not_searched(
    make_web_core: WebCore, student: Actor, other_student: Actor
) -> None:
    core, web = make_web_core()
    theirs = await make_notebook(core.uow_factory, other_student.user_id)

    with pytest.raises(NotebookNotFoundError):
        await DiscoverSources(core).execute(student, theirs.id, "topic")

    assert web.search.calls == []
    assert web.store.days == {}


@pytest.mark.parametrize("query", ["", " ", "a", "x" * 301])
async def test_a_request_of_the_wrong_length_is_refused_before_any_search(
    make_web_core: WebCore, student: Actor, query: str
) -> None:
    core, web = make_web_core()
    notebook = await make_notebook(core.uow_factory, student.user_id)

    with pytest.raises(InvalidOptionsError):
        await DiscoverSources(core).execute(student, notebook.id, query)

    assert web.store.days == {}


async def test_a_subject_notebook_the_system_keeps_cannot_take_web_sources(
    make_web_core: WebCore, student: Actor
) -> None:
    core, web = make_web_core()
    notebook = await make_notebook(
        core.uow_factory,
        student.user_id,
        origin=NotebookOrigin.SUBJECT_AUTO,
        subject_id=new_id(),
        auto_settings=AutoSettings(),
    )

    with pytest.raises(AutoNotebookReadOnlyError):
        await DiscoverSources(core).execute(student, notebook.id, "topic")

    assert web.search.calls == []


def test_the_fake_pages_are_distinct() -> None:
    assert page(1).url != page(2).url
