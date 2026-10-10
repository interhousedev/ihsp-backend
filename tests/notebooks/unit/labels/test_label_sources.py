"""G12/G13: the job `notebooks.label_sources` labels the selected sources by topic."""

from app.modules.notebooks.domain.entities import Notebook, Source
from app.modules.notebooks.domain.labels import LabelOrigin, LabelRunStatus
from app.modules.notebooks.domain.language import language_name
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.modules.notebooks.wiring_core import NotebooksCore
from app.modules.notebooks.wiring_labels import LabelsServices
from app.shared.actor import Actor
from app.shared.ai_tasks import AiTask
from app.shared.contracts.ai import AiInvalidOutputError, AiProviderError
from tests.factories.notebooks import make_source
from tests.fakes.clock import FixedClock
from tests.notebooks.unit.labels.conftest import GUIDE
from tests.notebooks.unit.labels.support import (
    answer,
    linked,
    names,
    run_of,
    running,
    store_label,
    store_link,
)
from tests.notebooks.unit.sources.support import HookedLlm

import pytest

WEIGHTED = 200  # the scripted usage: 100 input + 5 x 20 output


async def label_run(labels: LabelsServices, student: Actor, notebook: Notebook) -> None:
    """Start a run and execute the job it queued."""
    await labels.start_labeling.execute(student, notebook.id)
    await labels.label_sources.execute(notebook.id)


async def second_source(uow_factory: UowFactory, notebook: Notebook) -> Source:
    """A ready source without a guide."""
    return await make_source(uow_factory, notebook, title="History essay")


# - - - The model's answer is written - - -


async def test_the_selected_sources_get_the_labels_of_the_answer(
    labels: LabelsServices,
    uow_factory: UowFactory,
    scripted_llm: HookedLlm,
    clock: FixedClock,
    student: Actor,
    notebook: Notebook,
    source: Source,
) -> None:
    """G12: labels in order as `auto`, links by source key, run idle and finished."""
    other = await second_source(uow_factory, notebook)
    scripted_llm.queue_json(
        answer(
            [("Plants", "🌱"), ("History", "📜")],
            {"s1": ["l1"], "s2": ["l2", "l1"]},
        )
    )

    await label_run(labels, student, notebook)

    assert await names(uow_factory, notebook.id) == ["Plants", "History"]
    assert await linked(uow_factory, source.id) == {"Plants"}
    assert await linked(uow_factory, other.id) == {"History", "Plants"}
    async with uow_factory() as uow:
        stored = await uow.labels.list_for_notebook(notebook.id)
        links = await uow.labels.links_for_notebook(notebook.id)
    assert {x.origin for x in stored} == {LabelOrigin.AUTO}
    assert {x.origin for x in links} == {LabelOrigin.AUTO}
    assert [x.source_count for x in stored] == [2, 1]
    run = await run_of(uow_factory, notebook.id)
    assert (run.status, run.finished_at, run.error) == (
        LabelRunStatus.IDLE,
        clock.now(),
        None,
    )


async def test_the_request_has_the_titles_topics_summary_and_the_task_model(
    labels: LabelsServices,
    uow_factory: UowFactory,
    core: NotebooksCore,
    scripted_llm: HookedLlm,
    student: Actor,
    notebook: Notebook,
    source: Source,
) -> None:
    """G12: light task `source_labels`, strict schema, guide fields, title fallback."""
    await second_source(uow_factory, notebook)
    scripted_llm.queue_json(answer([("Plants", "🌱")], {"s1": ["l1"]}))

    await label_run(labels, student, notebook)

    (request,) = scripted_llm.json_requests
    assert request["schema_name"] == "nb_labels"
    assert request["model"] == core.llm.model(AiTask.SOURCE_LABELS)
    assert request["provider"]["data_collection"] == "deny"
    message = request["messages"][0]["content"]
    assert '<source key="s1" title="Biology 10">' in message
    assert "Key topics: Photosynthesis; Chloroplast" in message
    assert f"Summary: {GUIDE.summary}" in message
    assert '<source key="s2" title="History essay"></source>' in message
    assert (await core.budget.usage(student.user_id)).session.used == WEIGHTED


async def test_only_selected_ready_sources_are_sent(
    labels: LabelsServices,
    uow_factory: UowFactory,
    scripted_llm: HookedLlm,
    student: Actor,
    notebook: Notebook,
    source: Source,
) -> None:
    """G12: an unticked source is neither sent nor labeled."""
    unticked = await make_source(uow_factory, notebook, title="Skip me", selected=False)
    scripted_llm.queue_json(answer([("Plants", "🌱")], {"s1": ["l1"], "s2": ["l1"]}))

    await label_run(labels, student, notebook)

    message = scripted_llm.json_requests[0]["messages"][0]["content"]
    assert "Skip me" not in message and 's2"' not in message
    assert await linked(uow_factory, unticked.id) == set()


@pytest.mark.parametrize("user_locale", ["en", "ru", "uz"])
async def test_the_names_are_asked_in_the_locale_of_the_student(
    labels: LabelsServices,
    scripted_llm: HookedLlm,
    student: Actor,
    notebook: Notebook,
    source: Source,
    user_locale: str,
) -> None:
    """G12: the language of the user who clicked."""
    scripted_llm.queue_json(answer([("Plants", "🌱")], {"s1": ["l1"]}))

    await label_run(labels, student, notebook)

    assert language_name(user_locale) in scripted_llm.json_requests[0]["system"]


# - - - The student's labels are safe - - -


async def test_manual_labels_and_links_survive_a_second_run(
    labels: LabelsServices,
    uow_factory: UowFactory,
    scripted_llm: HookedLlm,
    student: Actor,
    notebook: Notebook,
    source: Source,
) -> None:
    """G12: nothing manual is renamed, deleted or overwritten; auto is replaced."""
    mine = await store_label(uow_factory, notebook.id, "Exam", position=1)
    await store_link(uow_factory, source.id, mine.id, LabelOrigin.MANUAL)
    scripted_llm.queue_json(answer([("Plants", "🌱")], {"s1": ["l1"]}))
    await label_run(labels, student, notebook)
    scripted_llm.queue_json(
        answer([("Sugar", "🍬"), ("exam", "📝")], {"s1": ["l1", "l2"]})
    )

    await label_run(labels, student, notebook)

    assert await names(uow_factory, notebook.id) == ["Exam", "Sugar"]
    assert await linked(uow_factory, source.id) == {"Exam", "Sugar"}
    async with uow_factory() as uow:
        exam = next(x for x in await uow.labels.list_for_notebook(notebook.id))
        links = await uow.labels.links_for_notebook(notebook.id)
    assert (exam.id, exam.origin) == (mine.id, LabelOrigin.MANUAL)
    assert {(x.label_id, x.origin) for x in links if x.label_id == mine.id} == {
        (mine.id, LabelOrigin.MANUAL)
    }
    second_request = scripted_llm.json_requests[1]["messages"][0]["content"]
    assert "<existing>\n- Exam\n</existing>" in second_request


async def test_auto_labels_no_longer_assigned_are_removed(
    labels: LabelsServices,
    uow_factory: UowFactory,
    scripted_llm: HookedLlm,
    student: Actor,
    notebook: Notebook,
    source: Source,
) -> None:
    """G12: the second run replaces the first run's topics."""
    scripted_llm.queue_json(answer([("Plants", "🌱")], {"s1": ["l1"]}))
    await label_run(labels, student, notebook)
    scripted_llm.queue_json(answer([("Sugar", "🍬")], {"s1": ["l1"]}))

    await label_run(labels, student, notebook)

    assert await names(uow_factory, notebook.id) == ["Sugar"]


async def test_a_source_outside_the_run_keeps_its_auto_labels(
    labels: LabelsServices,
    uow_factory: UowFactory,
    scripted_llm: HookedLlm,
    student: Actor,
    notebook: Notebook,
    source: Source,
) -> None:
    """G12: only the sources the run covered are relabeled."""
    other = await second_source(uow_factory, notebook)
    scripted_llm.queue_json(answer([("Plants", "🌱")], {"s1": ["l1"], "s2": ["l1"]}))
    await label_run(labels, student, notebook)
    async with uow_factory() as uow:
        await uow.sources.set_selected(notebook.id, False, [other.id])
        await uow.commit()
    scripted_llm.queue_json(answer([("Sugar", "🍬")], {"s1": ["l1"]}))

    await label_run(labels, student, notebook)

    assert await linked(uow_factory, source.id) == {"Sugar"}
    assert await linked(uow_factory, other.id) == {"Plants"}
    assert await names(uow_factory, notebook.id) == ["Plants", "Sugar"]


# - - - Defensive parsing - - -


async def test_unknown_source_keys_are_dropped(
    labels: LabelsServices,
    uow_factory: UowFactory,
    scripted_llm: HookedLlm,
    student: Actor,
    notebook: Notebook,
    source: Source,
) -> None:
    """G12: the model may invent `s7`; the real source is still labeled."""
    scripted_llm.queue_json(
        answer([("Plants", "🌱"), ("Ghost", "👻")], {"s1": ["l1"], "s7": ["l2"]})
    )

    await label_run(labels, student, notebook)

    assert await names(uow_factory, notebook.id) == ["Plants"]
    assert await linked(uow_factory, source.id) == {"Plants"}


async def test_at_most_twelve_labels_are_written(
    labels: LabelsServices,
    uow_factory: UowFactory,
    scripted_llm: HookedLlm,
    student: Actor,
    notebook: Notebook,
) -> None:
    """G12: fifteen proposals, twelve labels."""
    sources = [
        await make_source(uow_factory, notebook, title=f"Source {n}") for n in range(15)
    ]
    topics = [(f"Topic {n}", "🧬") for n in range(15)]
    scripted_llm.queue_json(
        answer(topics, {f"s{n + 1}": [f"l{n + 1}"] for n in range(15)})
    )

    await label_run(labels, student, notebook)

    assert len(await names(uow_factory, notebook.id)) == 12
    assert await linked(uow_factory, sources[14].id) == set()


# - - - Failures write nothing - - -


@pytest.mark.parametrize(
    "bad", [{"labels": [], "assignments": []}, {"nonsense": True}, {"labels": "x"}]
)
async def test_an_unusable_answer_fails_the_run_and_writes_nothing(
    labels: LabelsServices,
    uow_factory: UowFactory,
    scripted_llm: HookedLlm,
    student: Actor,
    notebook: Notebook,
    source: Source,
    bad: dict[str, object],
) -> None:
    """G12: status failed / invalid-output; the labels and links are as before."""
    mine = await store_label(uow_factory, notebook.id, "Exam")
    await store_link(uow_factory, source.id, mine.id)
    scripted_llm.queue_json(bad)

    await label_run(labels, student, notebook)

    run = await run_of(uow_factory, notebook.id)
    assert (run.status, run.error) == (LabelRunStatus.FAILED, "invalid-output")
    assert run.finished_at is not None
    assert await names(uow_factory, notebook.id) == ["Exam"]
    assert await linked(uow_factory, source.id) == {"Exam"}


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (AiProviderError(), "provider"),
        (AiInvalidOutputError(), "invalid-output"),
    ],
)
async def test_a_provider_failure_fails_the_run_after_the_retries(
    labels: LabelsServices,
    uow_factory: UowFactory,
    scripted_llm: HookedLlm,
    sleeps: list[float],
    student: Actor,
    notebook: Notebook,
    source: Source,
    error: Exception,
    reason: str,
) -> None:
    """G12: the light model is retried; then the run is `failed`, never a crash."""
    for _ in range(3):
        scripted_llm.queue_error(error)

    await label_run(labels, student, notebook)

    run = await run_of(uow_factory, notebook.id)
    assert (run.status, run.error) == (LabelRunStatus.FAILED, reason)
    assert await names(uow_factory, notebook.id) == []
    assert len(sleeps) == (2 if reason == "provider" else 0)


async def test_a_run_that_was_replaced_writes_nothing(
    labels: LabelsServices,
    uow_factory: UowFactory,
    clock: FixedClock,
    scripted_llm: HookedLlm,
    student: Actor,
    notebook: Notebook,
    source: Source,
) -> None:
    """G12: the run timed out and a newer one began while the model worked."""
    await labels.start_labeling.execute(student, notebook.id)
    original = clock.now()
    scripted_llm.queue_json(answer([("Plants", "🌱")], {"s1": ["l1"]}))

    async def newer_run() -> None:
        clock.advance(minutes=11)
        await labels.start_labeling.execute(student, notebook.id)

    scripted_llm.before_json = newer_run
    await labels.label_sources.execute(notebook.id)

    run = await run_of(uow_factory, notebook.id)
    assert (run.status, run.started_at) == (LabelRunStatus.RUNNING, clock.now())
    assert run.started_at != original
    assert await names(uow_factory, notebook.id) == []


async def test_a_job_without_a_running_run_does_nothing(
    labels: LabelsServices,
    scripted_llm: HookedLlm,
    notebook: Notebook,
    source: Source,
) -> None:
    """G12: a repeated or late kick makes no model call."""
    await labels.label_sources.execute(notebook.id)

    assert scripted_llm.calls == 0


async def test_sources_that_became_unselected_end_the_run_as_failed(
    labels: LabelsServices,
    uow_factory: UowFactory,
    clock: FixedClock,
    scripted_llm: HookedLlm,
    student: Actor,
    notebook: Notebook,
    source: Source,
) -> None:
    """G12: nothing selected when the job starts: failed / nothing-to-label."""
    await running(uow_factory, notebook.id, student.user_id, clock.now())
    async with uow_factory() as uow:
        await uow.sources.set_selected(notebook.id, False, None)
        await uow.commit()

    await labels.label_sources.execute(notebook.id)

    run = await run_of(uow_factory, notebook.id)
    assert (run.status, run.error) == (LabelRunStatus.FAILED, "nothing-to-label")
    assert scripted_llm.calls == 0
