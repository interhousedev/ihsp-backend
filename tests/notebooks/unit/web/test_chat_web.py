"""NB-32, NB-33: the web search toggle in the notebook chat."""

from app.modules.notebooks.wiring_chat import build_chat
from app.shared.actor import Actor
from app.shared.contracts.web_search import (
    SearchReply,
    WebSearchDisabledError,
    WebSearchQuotaError,
    WebSearchUnavailableError,
)
from tests.fakes.notebooks.llm import ScriptedLlm
from tests.notebooks.unit.chat.support import (
    ANSWER,
    collect,
    last_message,
    names,
    notebook_with_source,
    streamed_text,
    thread,
)
from tests.notebooks.unit.web.conftest import WebCore

import pytest

BOTH = (
    'Light becomes energy [[S1:P1]] and sugar [[W2]].\n<followups>["More?"]</followups>'
)


async def test_with_the_toggle_off_nothing_is_searched_and_nothing_is_added(
    make_web_core: WebCore, student: Actor, scripted_llm: ScriptedLlm
) -> None:
    """NB-32: the default question has no search, no web block and no web chips."""
    core, web = make_web_core()
    chat = build_chat(core)
    notebook, _ = await notebook_with_source(core, student)
    scripted_llm.queue_text(ANSWER)

    turn = await chat.ask_notebook.execute(student, notebook.id, "Q?")

    assert web.search.calls == []
    assert web.store.days == {}
    assert "web_results" not in last_message(scripted_llm.text_requests[0])
    assert turn.assistant_message.content.web == []


async def test_with_the_toggle_on_the_answer_cites_sources_and_web_pages(
    make_web_core: WebCore, student: Actor, scripted_llm: ScriptedLlm
) -> None:
    """NB-32: the question message ends with the pages; chips for both kinds."""
    core, web = make_web_core()
    chat = build_chat(core)
    notebook, _ = await notebook_with_source(core, student)
    scripted_llm.queue_text(BOTH)

    turn = await chat.ask_notebook.execute(
        student, notebook.id, "What is photosynthesis?", web_search=True
    )

    asked = last_message(scripted_llm.text_requests[0])
    assert asked.startswith("What is photosynthesis?")
    assert "rule 1 is extended" in asked
    assert "[W2] Photosynthesis 2 (school2.example.org)" in asked
    assert [call.query for call in web.search.calls] == ["What is photosynthesis?"]
    answer = turn.assistant_message.content
    assert answer.text == "Light becomes energy ⟦1⟧ and sugar ⟦w2⟧."
    assert [(c.n, c.source_title) for c in answer.citations] == [(1, "Biology")]
    assert [(r.n, r.cited) for r in answer.web] == [(1, False), (2, True), (3, False)]
    assert answer.web[1].url == "https://school2.example.org/photosynthesis"
    assert answer.grounded is True
    assert turn.user_message.content.web == []
    stored = await thread(core, student, notebook)
    assert [r.cited for r in stored[1].content.web] == [False, True, False]


async def test_an_answer_that_only_cites_the_web_is_grounded(
    make_web_core: WebCore, student: Actor, scripted_llm: ScriptedLlm
) -> None:
    core, _ = make_web_core()
    chat = build_chat(core)
    notebook, _ = await notebook_with_source(core, student)
    scripted_llm.queue_text("Only the web says so [[W1]] [[W7]].")

    turn = await chat.ask_notebook.execute(student, notebook.id, "Q?", web_search=True)

    answer = turn.assistant_message.content
    assert answer.text == "Only the web says so ⟦w1⟧."
    assert answer.citations == []
    assert answer.grounded is True


async def test_the_quota_counts_one_search_per_question_with_the_toggle_on(
    make_web_core: WebCore, student: Actor
) -> None:
    """NB-33: toggle on = one search; toggle off = free."""
    core, web = make_web_core()
    chat = build_chat(core)
    notebook, _ = await notebook_with_source(core, student)

    await chat.ask_notebook.execute(student, notebook.id, "one", web_search=True)
    await chat.ask_notebook.execute(student, notebook.id, "two")

    quota = await web.service.quota(student)
    assert (quota.used, quota.remaining) == (1, 9)


async def test_when_the_searches_are_used_up_the_question_is_refused_unstored(
    make_web_core: WebCore, student: Actor
) -> None:
    """NB-33: 429 before anything is stored; a question without search still works."""
    core, web = make_web_core(limits={"web_search_per_day_student": 1})
    chat = build_chat(core)
    notebook, _ = await notebook_with_source(core, student)
    await chat.ask_notebook.execute(student, notebook.id, "one", web_search=True)
    before = await thread(core, student, notebook)

    with pytest.raises(WebSearchQuotaError):
        await chat.ask_notebook.execute(student, notebook.id, "two", web_search=True)

    assert await thread(core, student, notebook) == before
    assert len(web.search.calls) == 1
    again = await chat.ask_notebook.execute(student, notebook.id, "three")
    assert again.assistant_message.content.web == []


async def test_with_the_feature_off_a_question_that_asks_for_search_is_refused(
    make_web_core: WebCore, student: Actor
) -> None:
    """NB-32: FEATURES__WEB_SEARCH=false."""
    core, web = make_web_core(features={"web_search": False})
    chat = build_chat(core)
    notebook, _ = await notebook_with_source(core, student)

    with pytest.raises(WebSearchDisabledError):
        await chat.ask_notebook.execute(student, notebook.id, "Q?", web_search=True)

    assert await thread(core, student, notebook) == []
    assert web.search.calls == []


async def test_without_a_search_service_the_toggle_is_disabled(
    make_web_core: WebCore, student: Actor
) -> None:
    core, _ = make_web_core(with_search=False)
    chat = build_chat(core)
    notebook, _ = await notebook_with_source(core, student)

    with pytest.raises(WebSearchDisabledError):
        await chat.ask_notebook.execute(student, notebook.id, "Q?", web_search=True)


async def test_a_failed_search_stores_nothing_and_costs_nothing(
    make_web_core: WebCore, student: Actor
) -> None:
    core, web = make_web_core()
    chat = build_chat(core)
    notebook, _ = await notebook_with_source(core, student)
    web.search.fail_next()

    with pytest.raises(WebSearchUnavailableError):
        await chat.ask_notebook.execute(student, notebook.id, "Q?", web_search=True)

    assert await thread(core, student, notebook) == []
    assert (await web.service.quota(student)).used == 0


async def test_a_search_with_no_pages_answers_from_the_sources_alone(
    make_web_core: WebCore, student: Actor, scripted_llm: ScriptedLlm
) -> None:
    core, web = make_web_core()
    chat = build_chat(core)
    notebook, _ = await notebook_with_source(core, student)
    web.search.push(SearchReply(hits=(), usage={}))
    scripted_llm.queue_text(ANSWER)

    turn = await chat.ask_notebook.execute(student, notebook.id, "Q?", web_search=True)

    assert "web_results" not in last_message(scripted_llm.text_requests[0])
    assert turn.assistant_message.content.web == []


async def test_regenerating_reuses_the_same_pages_without_a_new_search(
    make_web_core: WebCore, student: Actor, scripted_llm: ScriptedLlm
) -> None:
    """NB-33: the quota does not move on a regeneration."""
    core, web = make_web_core()
    chat = build_chat(core)
    notebook, _ = await notebook_with_source(core, student)
    scripted_llm.queue_text("First [[W1]].")
    await chat.ask_notebook.execute(student, notebook.id, "Q?", web_search=True)
    scripted_llm.queue_text("Second [[W3]].")

    turn = await chat.regenerate_chat.execute(student, notebook.id)

    assert len(web.search.calls) == 1
    assert (await web.service.quota(student)).used == 1
    assert "[W3] Photosynthesis 3" in last_message(scripted_llm.text_requests[-1])
    answer = turn.assistant_message.content
    assert answer.text == "Second ⟦w3⟧."
    assert [r.cited for r in answer.web] == [False, False, True]


# - - - streaming - - -


async def test_a_stream_sends_the_pages_then_the_text_with_whole_chips(
    make_web_core: WebCore, student: Actor, scripted_llm: ScriptedLlm
) -> None:
    """NB-32: `message`, `web`, then deltas; a marker split over chunks is held."""
    core, _ = make_web_core()
    chat = build_chat(core)
    notebook, _ = await notebook_with_source(core, student)
    scripted_llm.queue_stream(
        ["Light becomes energy [[S1:P1]] and ", "sugar [", "[W", "2, W", "3]].\n"]
    )

    events = await collect(
        chat.ask_notebook.stream(student, notebook.id, "Q?", web_search=True)
    )

    assert names(events)[:2] == ["message", "web"]
    assert names(events)[-1] == "done"
    pages = events[1].data["results"]
    assert [p["n"] for p in pages] == [1, 2, 3]
    shown = streamed_text(events)
    assert shown == "Light becomes energy ⟦1⟧ and sugar ⟦w2,3⟧."
    done = events[-1].data["message"]
    assert done["text"] == shown
    assert [(p["n"], p["cited"]) for p in done["web"]] == [
        (1, False),
        (2, True),
        (3, True),
    ]


async def test_a_stream_without_the_toggle_has_no_web_event(
    make_web_core: WebCore, student: Actor, scripted_llm: ScriptedLlm
) -> None:
    core, web = make_web_core()
    chat = build_chat(core)
    notebook, _ = await notebook_with_source(core, student)
    scripted_llm.queue_stream(["Fact [[S1:P1]]."])

    events = await collect(chat.ask_notebook.stream(student, notebook.id, "Q?"))

    assert "web" not in names(events)
    assert web.search.calls == []


async def test_a_stream_refuses_before_its_first_event_when_the_quota_is_gone(
    make_web_core: WebCore, student: Actor
) -> None:
    core, _ = make_web_core(limits={"web_search_per_day_student": 0})
    chat = build_chat(core)
    notebook, _ = await notebook_with_source(core, student)

    with pytest.raises(WebSearchDisabledError):
        await collect(
            chat.ask_notebook.stream(student, notebook.id, "Q?", web_search=True)
        )

    assert await thread(core, student, notebook) == []
