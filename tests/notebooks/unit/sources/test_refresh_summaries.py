"""NB-4: `notebooks.refresh_summaries` builds title, emoji and summary from guides."""

from datetime import timedelta
from typing import Any
from uuid import UUID

from app.modules.notebooks.application.notebook_state import selection_hash
from app.modules.notebooks.domain.entities import Notebook, SourceGuide
from app.modules.notebooks.domain.enums import GuideStatus, SourceStatus, SummaryStatus
from app.modules.notebooks.domain.language import language_name
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.modules.notebooks.wiring_core import NotebooksCore
from app.modules.notebooks.wiring_notebooks import build_notebooks
from app.modules.notebooks.wiring_sources import SourcesServices
from app.shared.actor import Actor
from app.shared.ai_tasks import AiTask
from app.shared.contracts.ai import AiInvalidOutputError, AiProviderError
from tests.factories.notebooks import make_notebook, make_source
from tests.fakes.clock import FixedClock
from tests.notebooks.unit.sources.conftest import Build
from tests.notebooks.unit.sources.support import (
    SUMMARY,
    HookedLlm,
    stored_notebook,
)

import pytest

WEIGHTED = 200  # the scripted usage: 100 input + 5 x 20 output


def _guide(title: str) -> SourceGuide:
    return SourceGuide(
        summary=f"{title} explained.",
        key_topics=[title],
        questions=[f"What is {title}?"],
    )


async def _due(
    uow_factory: UowFactory, actor: Actor, clock: FixedClock, **fields: Any
) -> Notebook:
    """A notebook whose summary is due now."""
    fields.setdefault("summary_status", SummaryStatus.STALE)
    fields.setdefault("summary_due_at", clock.now())
    return await make_notebook(uow_factory, actor.user_id, **fields)


async def _with_guide(
    uow_factory: UowFactory, notebook: Notebook, title: str, **fields: Any
) -> UUID:
    values: dict[str, Any] = {
        "guide": _guide(title),
        "guide_status": GuideStatus.READY,
        "texts": (f"{title} is a topic of the lesson.",),
    }
    values.update(fields)
    return (await make_source(uow_factory, notebook, title=title, **values)).id


async def _current_hash(uow_factory: UowFactory, notebook: Notebook) -> str:
    async with uow_factory() as uow:
        return selection_hash(await uow.sources.list_for_notebook(notebook.id))


# - - - Building - - -


async def test_the_summary_is_built_from_the_guides_of_the_selected_sources(
    sources: SourcesServices,
    uow_factory: UowFactory,
    core: NotebooksCore,
    scripted_llm: HookedLlm,
    student: Actor,
    clock: FixedClock,
) -> None:
    """NB-4: title, emoji, overview and questions come from guides, not full texts."""
    notebook = await _due(uow_factory, student, clock)
    await _with_guide(uow_factory, notebook, "Cells")
    await _with_guide(uow_factory, notebook, "Genes")
    scripted_llm.queue_json(SUMMARY)

    assert await sources.refresh_summaries.execute() == 1

    saved = await stored_notebook(uow_factory, notebook.id)
    assert (saved.title, saved.emoji) == ("Plant energy", "🌱")
    assert saved.summary is not None
    assert saved.summary.summary == SUMMARY["summary"]
    assert saved.summary.key_topics == SUMMARY["key_topics"]
    assert saved.summary.suggested_questions == SUMMARY["suggested_questions"]
    assert saved.summary.generated_at == clock.now()
    assert (saved.summary_status, saved.summary_due_at) == (SummaryStatus.READY, None)
    assert saved.summary_hash == await _current_hash(uow_factory, notebook)
    (request,) = scripted_llm.json_requests
    assert request["schema_name"] == "nb_summary"
    assert request["model"] == core.llm.model(AiTask.NOTEBOOK_SUMMARY)
    prompt = request["messages"][0]["content"]
    assert '<guide n="1" title="Cells">' in prompt
    assert '<guide n="2" title="Genes">' in prompt
    assert "Summary: Cells explained." in prompt
    assert (await core.budget.usage(student.user_id)).session.used == WEIGHTED


@pytest.mark.parametrize(
    ("user_locale", "language"), [("en", "en"), ("ru", "ru"), ("uz", "uz")]
)
async def test_the_summary_is_written_in_the_students_language(
    sources: SourcesServices,
    uow_factory: UowFactory,
    scripted_llm: HookedLlm,
    student: Actor,
    clock: FixedClock,
    language: str,
) -> None:
    """NB-4: the language follows the locale of the notebook's owner."""
    notebook = await _due(uow_factory, student, clock)
    await _with_guide(uow_factory, notebook, "Cells")
    scripted_llm.queue_json(SUMMARY)

    await sources.refresh_summaries.execute()

    assert language_name(language) in scripted_llm.json_requests[0]["system"]


async def test_a_summary_waits_until_it_is_due(
    sources: SourcesServices,
    uow_factory: UowFactory,
    scripted_llm: HookedLlm,
    student: Actor,
    clock: FixedClock,
) -> None:
    """NB-4: the 20 second debounce: not before `summary_due_at`."""
    notebook = await _due(
        uow_factory, student, clock, summary_due_at=clock.now() + timedelta(seconds=20)
    )
    await _with_guide(uow_factory, notebook, "Cells")
    scripted_llm.queue_json(SUMMARY)

    assert await sources.refresh_summaries.execute() == 0
    assert scripted_llm.calls == 0
    assert (
        await stored_notebook(uow_factory, notebook.id)
    ).summary_status is SummaryStatus.STALE

    clock.advance(seconds=20)
    assert await sources.refresh_summaries.execute() == 1


async def test_a_name_and_emoji_chosen_by_the_student_are_kept(
    sources: SourcesServices,
    uow_factory: UowFactory,
    scripted_llm: HookedLlm,
    student: Actor,
    clock: FixedClock,
) -> None:
    """NB-4: only automatic titles and emojis are replaced; the overview is stored."""
    notebook = await _due(
        uow_factory,
        student,
        clock,
        title="My biology",
        title_auto=False,
        emoji="📘",
        emoji_auto=False,
    )
    await _with_guide(uow_factory, notebook, "Cells")
    scripted_llm.queue_json(SUMMARY)

    await sources.refresh_summaries.execute()

    saved = await stored_notebook(uow_factory, notebook.id)
    assert (saved.title, saved.emoji) == ("My biology", "📘")
    assert saved.summary is not None
    assert saved.summary_status is SummaryStatus.READY


async def test_an_unchanged_selection_is_not_summarised_again(
    sources: SourcesServices,
    uow_factory: UowFactory,
    scripted_llm: HookedLlm,
    student: Actor,
    clock: FixedClock,
) -> None:
    """NB-4: the summary is rebuilt only when the selection hash really changed."""
    notebook = await _due(uow_factory, student, clock)
    await _with_guide(uow_factory, notebook, "Cells")
    scripted_llm.queue_json(SUMMARY)
    await sources.refresh_summaries.execute()
    async with uow_factory() as uow:
        again = await uow.notebooks.get_for_update(notebook.id)
        assert again is not None
        again.summary_status = SummaryStatus.STALE
        again.summary_due_at = clock.now()
        await uow.notebooks.save(again)
        await uow.commit()

    assert await sources.refresh_summaries.execute() == 0

    assert scripted_llm.calls == 1
    saved = await stored_notebook(uow_factory, notebook.id)
    assert (saved.summary_status, saved.summary_due_at) == (SummaryStatus.READY, None)


async def test_a_notebook_without_selected_usable_sources_has_no_summary(
    sources: SourcesServices,
    uow_factory: UowFactory,
    scripted_llm: HookedLlm,
    student: Actor,
    clock: FixedClock,
) -> None:
    """NB-4, NB-5: unticked, failed and unavailable sources do not count."""
    notebook = await _due(uow_factory, student, clock)
    await _with_guide(uow_factory, notebook, "Cells", selected=False)
    await _with_guide(uow_factory, notebook, "Genes", status=SourceStatus.FAILED)

    assert await sources.refresh_summaries.execute() == 0

    saved = await stored_notebook(uow_factory, notebook.id)
    assert (saved.summary_status, saved.summary_due_at) == (SummaryStatus.NONE, None)
    assert scripted_llm.calls == 0


async def test_deleted_notebooks_and_notebooks_not_due_are_skipped(
    sources: SourcesServices,
    uow_factory: UowFactory,
    scripted_llm: HookedLlm,
    student: Actor,
    clock: FixedClock,
) -> None:
    """NB-4: soft-deleted notebooks and settled ones cost no model call."""
    gone = await _due(uow_factory, student, clock, deleted_at=clock.now())
    await _with_guide(uow_factory, gone, "Cells")
    quiet = await make_notebook(uow_factory, student.user_id)
    await _with_guide(uow_factory, quiet, "Genes")

    assert await sources.refresh_summaries.execute() == 0
    assert scripted_llm.calls == 0


async def test_at_most_20_summaries_are_built_per_run(
    sources: SourcesServices,
    uow_factory: UowFactory,
    scripted_llm: HookedLlm,
    student: Actor,
    clock: FixedClock,
) -> None:
    """NB-4: the cron runs every minute and takes 20 notebooks at a time."""
    for n in range(21):
        notebook = await _due(uow_factory, student, clock, title=f"Notebook {n}")
        await _with_guide(uow_factory, notebook, f"Topic {n}")
        scripted_llm.queue_json(SUMMARY)

    assert await sources.refresh_summaries.execute() == 20
    assert await sources.refresh_summaries.execute() == 1
    assert scripted_llm.calls == 21


# - - - Guides that are not ready - - -


async def test_unfinished_guides_postpone_the_summary_for_a_minute(
    sources: SourcesServices,
    uow_factory: UowFactory,
    scripted_llm: HookedLlm,
    student: Actor,
    clock: FixedClock,
) -> None:
    """NB-4: a source whose guide is still being written is waited for."""
    notebook = await _due(uow_factory, student, clock)
    await _with_guide(uow_factory, notebook, "Cells")
    await _with_guide(
        uow_factory,
        notebook,
        "Genes",
        guide=None,
        guide_status=GuideStatus.BUILDING,
        updated_at=clock.now(),
    )

    assert await sources.refresh_summaries.execute() == 0

    saved = await stored_notebook(uow_factory, notebook.id)
    assert saved.summary_status is SummaryStatus.STALE
    assert saved.summary_due_at == clock.now() + timedelta(seconds=60)
    assert scripted_llm.calls == 0


async def test_a_guide_that_never_arrives_is_left_out_after_ten_minutes(
    sources: SourcesServices,
    uow_factory: UowFactory,
    scripted_llm: HookedLlm,
    student: Actor,
    clock: FixedClock,
) -> None:
    """NB-4: the summary is built from the guides there are."""
    notebook = await _due(uow_factory, student, clock)
    await _with_guide(uow_factory, notebook, "Cells")
    await _with_guide(
        uow_factory, notebook, "Genes", guide=None, guide_status=GuideStatus.BUILDING
    )
    clock.advance(minutes=11)
    scripted_llm.queue_json(SUMMARY)

    assert await sources.refresh_summaries.execute() == 1

    prompt = scripted_llm.json_requests[0]["messages"][0]["content"]
    assert 'title="Cells"' in prompt
    assert 'title="Genes"' not in prompt


async def test_without_any_guide_the_summary_fails_without_a_model_call(
    sources: SourcesServices,
    uow_factory: UowFactory,
    scripted_llm: HookedLlm,
    student: Actor,
    clock: FixedClock,
) -> None:
    """NB-4: every guide failed; there is nothing to summarise."""
    notebook = await _due(uow_factory, student, clock)
    await _with_guide(
        uow_factory, notebook, "Cells", guide=None, guide_status=GuideStatus.FAILED
    )

    assert await sources.refresh_summaries.execute() == 0

    saved = await stored_notebook(uow_factory, notebook.id)
    assert (saved.summary_status, saved.summary_due_at) == (SummaryStatus.FAILED, None)
    assert scripted_llm.calls == 0


# - - - Failures - - -


async def test_a_provider_error_is_retried_and_then_succeeds(
    sources: SourcesServices,
    uow_factory: UowFactory,
    scripted_llm: HookedLlm,
    student: Actor,
    clock: FixedClock,
    sleeps: list[float],
) -> None:
    """NB-4: the same retries as the guides."""
    notebook = await _due(uow_factory, student, clock)
    await _with_guide(uow_factory, notebook, "Cells")
    scripted_llm.queue_error(AiProviderError())
    scripted_llm.queue_json(SUMMARY)

    assert await sources.refresh_summaries.execute() == 1

    assert sleeps == [2.0]
    saved = await stored_notebook(uow_factory, notebook.id)
    assert saved.summary_status is SummaryStatus.READY


@pytest.mark.parametrize(
    "answers",
    [
        [AiProviderError(), AiProviderError(), AiProviderError()],
        [AiInvalidOutputError()],
        [{**SUMMARY, "summary": " "}],
    ],
)
async def test_a_summary_that_cannot_be_built_is_failed_and_nothing_is_overwritten(
    sources: SourcesServices,
    uow_factory: UowFactory,
    scripted_llm: HookedLlm,
    student: Actor,
    clock: FixedClock,
    answers: list[Any],
) -> None:
    """NB-4: the title stays; the status is `failed` and it is not retried."""
    notebook = await _due(uow_factory, student, clock, title="Untitled notebook")
    await _with_guide(uow_factory, notebook, "Cells")
    for answer in answers:
        if isinstance(answer, AiProviderError):
            scripted_llm.queue_error(answer)
        else:
            scripted_llm.queue_json(answer)

    assert await sources.refresh_summaries.execute() == 0

    saved = await stored_notebook(uow_factory, notebook.id)
    assert (saved.summary_status, saved.summary_due_at) == (SummaryStatus.FAILED, None)
    assert (saved.summary, saved.title) == (None, "Untitled notebook")


async def test_an_empty_budget_fails_the_summary_without_a_model_call(
    build: Build,
    uow_factory: UowFactory,
    scripted_llm: HookedLlm,
    student: Actor,
    clock: FixedClock,
) -> None:
    """NB-14, NB-4: the student's budget is used up."""
    sources = build(limits={"nb_session_tokens_student": 10})
    notebook = await _due(uow_factory, student, clock)
    await _with_guide(uow_factory, notebook, "Cells")

    assert await sources.refresh_summaries.execute() == 0

    saved = await stored_notebook(uow_factory, notebook.id)
    assert saved.summary_status is SummaryStatus.FAILED
    assert scripted_llm.calls == 0


# - - - Changes while the model works - - -


async def test_a_selection_changed_during_the_call_wins_over_the_summary(
    sources: SourcesServices,
    uow_factory: UowFactory,
    scripted_llm: HookedLlm,
    student: Actor,
    clock: FixedClock,
) -> None:
    """NB-4, NB-5: an answer about the old selection is dropped; a new one is due."""
    notebook = await _due(uow_factory, student, clock)
    cells = await _with_guide(uow_factory, notebook, "Cells")
    await _with_guide(uow_factory, notebook, "Genes")

    async def untick_while_the_model_works() -> None:
        scripted_llm.before_json = None
        await sources.select_sources.execute(student, notebook.id, False, [cells])

    scripted_llm.before_json = untick_while_the_model_works
    scripted_llm.queue_json(SUMMARY)

    assert await sources.refresh_summaries.execute() == 0

    saved = await stored_notebook(uow_factory, notebook.id)
    assert saved.summary is None
    assert saved.title == notebook.title
    assert saved.summary_status is SummaryStatus.STALE
    assert saved.summary_due_at == clock.now() + timedelta(seconds=20)


async def test_a_building_summary_is_stamped_so_the_stuck_sweep_leaves_it_alone(
    sources: SourcesServices,
    uow_factory: UowFactory,
    core: NotebooksCore,
    scripted_llm: HookedLlm,
    student: Actor,
    clock: FixedClock,
) -> None:
    """NB-4: `building` carries the time it started, not the time of the last edit."""
    notebook = await _due(uow_factory, student, clock)
    await _with_guide(uow_factory, notebook, "Cells")
    clock.advance(hours=1)
    started = clock.now()
    seen: dict[str, Any] = {}

    async def look_while_the_model_works() -> None:
        scripted_llm.before_json = None
        building = await stored_notebook(uow_factory, notebook.id)
        seen["status"] = building.summary_status
        seen["updated_at"] = building.updated_at
        clock.advance(minutes=9)
        seen["swept"] = (await build_notebooks(core).sweep_stuck.execute())["summaries"]

    scripted_llm.before_json = look_while_the_model_works
    scripted_llm.queue_json(SUMMARY)

    assert await sources.refresh_summaries.execute() == 1

    assert seen["status"] is SummaryStatus.BUILDING
    assert seen["updated_at"] == started
    assert seen["swept"] == 0
    saved = await stored_notebook(uow_factory, notebook.id)
    assert saved.summary_status is SummaryStatus.READY
