"""NB-8, NB-9, NB-14, NB-20: the job that turns a request into a Studio output."""

import asyncio
import json
from typing import Any

from app.modules.notebooks.application.artifact_tasks import task_for_kind
from app.modules.notebooks.domain.entities import Notebook, Source
from app.modules.notebooks.domain.enums import ArtifactKind, ArtifactStatus
from app.modules.notebooks.domain.tokens import Usage
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.modules.notebooks.wiring_core import NotebooksCore
from app.modules.notebooks.wiring_studio import StudioServices
from app.shared.actor import Actor
from app.shared.contracts.ai import AiInvalidOutputError, AiProviderError
from app.shared.notifications import NotificationDraft, NotificationType
from tests.factories.notebooks import make_notebook, make_source
from tests.fakes.clock import FixedClock
from tests.notebooks.unit.studio.helpers import (
    BAD_REPORT,
    Build,
    HookedLlm,
    big_texts,
    generate,
    stored,
)

import pytest

CONSPECT = {"format": "conspect"}
REPORT_FORMATS = ["conspect", "study_guide", "briefing", "faq", "timeline", "article"]
KIND_CASES = [
    pytest.param(ArtifactKind.REPORT, {"format": name}, None, id=f"report-{name}")
    for name in REPORT_FORMATS
] + [
    pytest.param(
        ArtifactKind.REPORT,
        {"format": "custom"},
        "Compare the two stages",
        id="report-custom",
    ),
    pytest.param(ArtifactKind.MIND_MAP, {}, None, id="mind-map"),
    pytest.param(ArtifactKind.FLASHCARDS, {}, None, id="flashcards"),
    pytest.param(ArtifactKind.QUIZ, {}, None, id="quiz"),
    pytest.param(ArtifactKind.DATA_TABLE, {}, None, id="data-table"),
    pytest.param(ArtifactKind.SLIDES, {}, None, id="slides"),
    pytest.param(ArtifactKind.INFOGRAPHIC, {}, None, id="infographic"),
]
ITEMS_KEY = {
    ArtifactKind.MIND_MAP: "nodes",
    ArtifactKind.FLASHCARDS: "cards",
    ArtifactKind.QUIZ: "questions",
    ArtifactKind.DATA_TABLE: "rows",
    ArtifactKind.SLIDES: "slides",
    ArtifactKind.INFOGRAPHIC: "blocks",
}


async def used_today(core: NotebooksCore, actor: Actor) -> int:
    """How many outputs were requested today (the `artifacts` counter)."""
    return (await core.quota.snapshot(actor.user_id))["artifacts"].used


async def spent_today(core: NotebooksCore, actor: Actor) -> int:
    """Weighted tokens counted against the day budget."""
    return (await core.budget.usage(actor.user_id)).day.used


@pytest.mark.parametrize(("kind", "options", "prompt"), KIND_CASES)
async def test_each_kind_is_generated_end_to_end(
    studio: StudioServices,
    core: NotebooksCore,
    student: Actor,
    notebook: Notebook,
    source: Source,
    uow_factory: UowFactory,
    clock: FixedClock,
    kind: ArtifactKind,
    options: dict[str, Any],
    prompt: str | None,
) -> None:
    """NB-8, NB-20: request -> job -> ready with a validated document and refs."""
    artifact = await generate(
        studio, uow_factory, student, notebook, kind, options, prompt
    )

    content = artifact.content
    assert artifact.status is ArtifactStatus.READY
    assert artifact.error is None
    assert content is not None
    assert artifact.title
    assert artifact.finished_at == clock.now()
    assert artifact.model == core.llm.model(task_for_kind(kind))
    assert (artifact.tokens_in or 0) > 0
    assert (artifact.weighted or 0) > 0
    assert artifact.source_map == {"S1": str(source.id)}
    assert artifact.sampled is False
    if kind is ArtifactKind.REPORT:
        assert "⟦1⟧" in content["markdown"]
        assert content["citations"][0]["n"] == 1
        assert artifact.refs_index == {}
    else:
        assert content[ITEMS_KEY[kind]]
        assert artifact.refs_index
        assert all(label.startswith("S1:P") for label in artifact.refs_index)


async def test_finished_output_frees_the_slot_and_counts_the_budget(
    studio: StudioServices,
    core: NotebooksCore,
    student: Actor,
    notebook: Notebook,
    source: Source,
    uow_factory: UowFactory,
) -> None:
    """NB-14: the weighted tokens of the call are counted; the slot is free again."""
    artifact = await generate(
        studio, uow_factory, student, notebook, ArtifactKind.REPORT, CONSPECT
    )

    assert await spent_today(core, student) == artifact.weighted
    assert await core.quota.running_count(student.user_id) == 0
    assert await used_today(core, student) == 1


async def test_model_call_has_the_documented_shape(
    studio: StudioServices,
    student: Actor,
    notebook: Notebook,
    source: Source,
    uow_factory: UowFactory,
    scripted_llm: HookedLlm,
) -> None:
    """NB-16, NB-20: strict schema, privacy options, the sources block, the task."""
    await generate(
        studio, uow_factory, student, notebook, ArtifactKind.REPORT, CONSPECT
    )

    request = scripted_llm.json_requests[0]
    messages = request["messages"]
    assert request["schema_name"] == "nb_report"
    assert request["schema"]["additionalProperties"] is False
    assert request["max_tokens"] == 8000
    assert request["provider"] == {
        "data_collection": "deny",
        "require_parameters": True,
    }
    assert request["system"].startswith(
        "You turn study sources into learning materials"
    )
    assert [m["role"] for m in messages] == ["user", "user"]
    assert "<sources>" in json.dumps(messages[0])
    assert "[S1:P1]" in json.dumps(messages[0])
    assert "conspect" in messages[1]["content"]


@pytest.mark.parametrize(
    ("options", "expected"),
    [({}, "English"), ({"language": "ru"}, "Russian"), ({"language": "uz"}, "Uzbek")],
)
async def test_language_is_the_option_else_the_locale_of_the_owner(
    studio: StudioServices,
    student: Actor,
    notebook: Notebook,
    source: Source,
    uow_factory: UowFactory,
    scripted_llm: HookedLlm,
    options: dict[str, Any],
    expected: str,
) -> None:
    """NB-8: `language` of the options, else the user's locale (here `en`)."""
    await generate(
        studio, uow_factory, student, notebook, ArtifactKind.MIND_MAP, options
    )

    assert expected in scripted_llm.json_requests[0]["system"]


async def test_running_the_job_twice_generates_once_and_notifies_once(
    studio: StudioServices,
    student: Actor,
    notebook: Notebook,
    source: Source,
    uow_factory: UowFactory,
    scripted_llm: HookedLlm,
    outbox: list[NotificationDraft],
) -> None:
    """NB-9: the job takes the row only from `queued`; one bell entry per output."""
    queued = await studio.request_artifact.execute(
        student, notebook.id, ArtifactKind.MIND_MAP, {}, None
    )

    await studio.generate_artifact.execute(queued.id)
    await studio.generate_artifact.execute(queued.id)

    row = await stored(uow_factory, queued.id)
    assert (row.status, row.attempts) == (ArtifactStatus.READY, 1)
    assert scripted_llm.calls == 1
    assert len(outbox) == 1
    draft = outbox[0]
    assert draft.type is NotificationType.NOTEBOOK_ARTIFACT_READY
    assert draft.user_id == student.user_id
    assert draft.dedupe_key == f"notebook_artifact_ready:{queued.id}"
    assert draft.payload == {
        "notebook_id": str(notebook.id),
        "artifact_id": str(queued.id),
        "kind": "mind_map",
        "title": row.title,
    }


async def test_big_notebook_is_sampled(
    build: Build,
    student: Actor,
    notebook: Notebook,
    uow_factory: UowFactory,
    scripted_llm: HookedLlm,
) -> None:
    """NB-8: text over the Studio cap is sampled; the output says so."""
    await make_source(uow_factory, notebook, texts=big_texts(), title="Big")
    studio = build(notebooks={"studio_context_tokens": 150})

    artifact = await generate(
        studio, uow_factory, student, notebook, ArtifactKind.REPORT, CONSPECT
    )

    sent = json.dumps(scripted_llm.json_requests[0]["messages"][0])
    assert artifact.status is ArtifactStatus.READY
    assert artifact.sampled is True
    assert 0 < sent.count("[S1:P") < 12


# - - - Repair call - - -


async def test_invalid_document_gets_one_repair_call(
    studio: StudioServices,
    core: NotebooksCore,
    student: Actor,
    notebook: Notebook,
    source: Source,
    uow_factory: UowFactory,
    scripted_llm: HookedLlm,
) -> None:
    """NB-20: a document that breaks a rule is repaired with ONE more call."""
    scripted_llm.queue_json(BAD_REPORT)

    artifact = await generate(
        studio, uow_factory, student, notebook, ArtifactKind.REPORT, CONSPECT
    )

    repair = scripted_llm.json_requests[1]["messages"]
    assert artifact.status is ArtifactStatus.READY
    assert scripted_llm.calls == 2
    assert [m["role"] for m in repair] == ["user", "user", "assistant", "user"]
    assert repair[2]["content"] == json.dumps(BAD_REPORT)
    assert "too short" in repair[3]["content"]
    assert await spent_today(core, student) == artifact.weighted


async def test_answer_that_is_not_json_gets_a_repair_call_too(
    studio: StudioServices,
    student: Actor,
    notebook: Notebook,
    source: Source,
    uow_factory: UowFactory,
    scripted_llm: HookedLlm,
) -> None:
    """NB-20: the gateway's invalid-output error also leads to the repair call."""
    scripted_llm.queue_error(AiInvalidOutputError())

    artifact = await generate(
        studio, uow_factory, student, notebook, ArtifactKind.MIND_MAP, {}
    )

    repair = scripted_llm.json_requests[1]["messages"]
    assert artifact.status is ArtifactStatus.READY
    assert [m["role"] for m in repair] == ["user", "user", "user"]
    assert "not a JSON object" in repair[2]["content"]


async def test_invalid_twice_fails_with_invalid_output(
    studio: StudioServices,
    core: NotebooksCore,
    student: Actor,
    notebook: Notebook,
    source: Source,
    uow_factory: UowFactory,
    scripted_llm: HookedLlm,
    clock: FixedClock,
    outbox: list[NotificationDraft],
) -> None:
    """NB-20: still invalid after the repair -> failed; both calls are counted."""
    scripted_llm.queue_json(BAD_REPORT)
    scripted_llm.queue_json(BAD_REPORT)

    artifact = await generate(
        studio, uow_factory, student, notebook, ArtifactKind.REPORT, CONSPECT
    )

    assert artifact.status is ArtifactStatus.FAILED
    assert artifact.error is not None
    assert artifact.error.code == "invalid_output"
    assert artifact.error.message_key == "notebooks-artifact-error-invalid-output"
    assert artifact.content is None
    assert artifact.finished_at == clock.now()
    assert scripted_llm.calls == 2
    assert artifact.tokens_in == 200
    assert await spent_today(core, student) == 400
    assert await used_today(core, student) == 1  # the model answered: it counts
    assert await core.quota.running_count(student.user_id) == 0
    assert outbox == []


# - - - Provider errors, timeout, no content - - -


async def test_provider_error_is_retried_with_backoff(
    studio: StudioServices,
    student: Actor,
    notebook: Notebook,
    source: Source,
    uow_factory: UowFactory,
    scripted_llm: HookedLlm,
    sleeps: list[float],
) -> None:
    """NB-9: a provider error is retried; one failure then success is `ready`."""
    scripted_llm.queue_error(AiProviderError())

    artifact = await generate(
        studio, uow_factory, student, notebook, ArtifactKind.MIND_MAP, {}
    )

    assert artifact.status is ArtifactStatus.READY
    assert scripted_llm.calls == 2
    assert sleeps == [2.0]


async def test_provider_error_three_times_fails_and_gives_the_count_back(
    studio: StudioServices,
    core: NotebooksCore,
    student: Actor,
    notebook: Notebook,
    source: Source,
    uow_factory: UowFactory,
    scripted_llm: HookedLlm,
    sleeps: list[float],
) -> None:
    """NB-14: after two retries the output fails; the daily count is released."""
    for _ in range(3):
        scripted_llm.queue_error(AiProviderError())

    artifact = await generate(
        studio, uow_factory, student, notebook, ArtifactKind.QUIZ, {}
    )

    assert artifact.status is ArtifactStatus.FAILED
    assert artifact.error is not None
    assert artifact.error.code == "provider_error"
    assert artifact.error.message_key == "notebooks-artifact-error-provider"
    assert scripted_llm.calls == 3
    assert sleeps == [2.0, 6.0]
    assert await used_today(core, student) == 0
    assert await spent_today(core, student) == 0
    assert await core.quota.running_count(student.user_id) == 0


async def test_slow_model_times_out_and_gives_the_count_back(
    build: Build,
    core: NotebooksCore,
    student: Actor,
    notebook: Notebook,
    source: Source,
    uow_factory: UowFactory,
    scripted_llm: HookedLlm,
) -> None:
    """NB-9: a call over the timeout fails the output with `timeout`."""
    studio = build(notebooks={"llm_timeout_seconds": 0.05})

    async def stall() -> None:
        await asyncio.sleep(5)

    scripted_llm.before_json = stall

    artifact = await generate(
        studio, uow_factory, student, notebook, ArtifactKind.QUIZ, {}
    )

    assert artifact.status is ArtifactStatus.FAILED
    assert artifact.error is not None
    assert artifact.error.code == "timeout"
    assert artifact.error.message_key == "notebooks-artifact-error-timeout"
    assert await used_today(core, student) == 0
    assert await core.quota.running_count(student.user_id) == 0


async def test_sources_too_thin_fail_with_no_content(
    studio: StudioServices,
    core: NotebooksCore,
    student: Actor,
    uow_factory: UowFactory,
    scripted_llm: HookedLlm,
) -> None:
    """NB-9: sources under about 8 tokens give `no_content` without a model call."""
    thin = await make_notebook(uow_factory, student.user_id)
    await make_source(uow_factory, thin, texts=("A very short note.",))

    artifact = await generate(studio, uow_factory, student, thin, ArtifactKind.QUIZ, {})

    assert artifact.status is ArtifactStatus.FAILED
    assert artifact.error is not None
    assert artifact.error.code == "no_content"
    assert artifact.error.message_key == "notebooks-artifact-error-no-content"
    assert scripted_llm.calls == 0
    assert await used_today(core, student) == 0


async def test_sources_removed_before_the_job_runs_fail_with_no_content(
    studio: StudioServices,
    student: Actor,
    notebook: Notebook,
    source: Source,
    uow_factory: UowFactory,
    scripted_llm: HookedLlm,
) -> None:
    """NB-9: the job uses the sources that still exist; none left -> `no_content`."""
    queued = await studio.request_artifact.execute(
        student, notebook.id, ArtifactKind.QUIZ, {}, None
    )
    async with uow_factory() as uow:
        await uow.sources.delete(source.id)
        await uow.commit()

    await studio.generate_artifact.execute(queued.id)

    row = await stored(uow_factory, queued.id)
    assert row.status is ArtifactStatus.FAILED
    assert row.error is not None
    assert row.error.code == "no_content"
    assert scripted_llm.calls == 0


async def test_job_fails_when_the_budget_ran_out_in_the_queue(
    studio: StudioServices,
    core: NotebooksCore,
    student: Actor,
    notebook: Notebook,
    source: Source,
    uow_factory: UowFactory,
    scripted_llm: HookedLlm,
) -> None:
    """NB-14: budget used up while waiting -> `limit_reached`, no call, count back."""
    queued = await studio.request_artifact.execute(
        student, notebook.id, ArtifactKind.QUIZ, {}, None
    )
    await core.budget.add(student.user_id, 4_000_000)

    await studio.generate_artifact.execute(queued.id)

    row = await stored(uow_factory, queued.id)
    assert row.status is ArtifactStatus.FAILED
    assert row.error is not None
    assert row.error.code == "limit_reached"
    assert row.error.message_key == "notebooks-artifact-error-limit-reached"
    assert set(row.error.params) == {"scope", "resets_at"}
    assert scripted_llm.calls == 0
    assert await used_today(core, student) == 0


async def test_unexpected_error_fails_the_output_instead_of_hanging(
    studio: StudioServices,
    core: NotebooksCore,
    student: Actor,
    notebook: Notebook,
    source: Source,
    uow_factory: UowFactory,
    scripted_llm: HookedLlm,
) -> None:
    """NB-9: a bug in the job must not leave the output `generating` for ever."""
    scripted_llm.queue_error(RuntimeError("boom"))

    artifact = await generate(
        studio, uow_factory, student, notebook, ArtifactKind.QUIZ, {}
    )

    assert artifact.status is ArtifactStatus.FAILED
    assert artifact.error is not None
    assert artifact.error.code == "provider_error"
    assert await used_today(core, student) == 0
    assert await core.quota.running_count(student.user_id) == 0


# - - - Budget - - -


async def test_every_call_is_counted_in_the_budget_with_its_cached_tokens(
    studio: StudioServices,
    core: NotebooksCore,
    student: Actor,
    notebook: Notebook,
    source: Source,
    uow_factory: UowFactory,
    scripted_llm: HookedLlm,
) -> None:
    """NB-14: weighted = uncached + 0.1 x cached + 5 x output, for failed calls too."""
    first = {"input": 1000, "output": 100, "cached": 500, "cost_micro": 1200}
    second = {"input": 800, "output": 50, "cached": 0, "cost_micro": 800}
    scripted_llm.queue_json(BAD_REPORT, usage=first)
    scripted_llm.queue_json(BAD_REPORT, usage=second)
    expected_first = Usage.from_gateway(first)
    expected_second = Usage.from_gateway(second)

    artifact = await generate(
        studio, uow_factory, student, notebook, ArtifactKind.REPORT, CONSPECT
    )

    assert artifact.status is ArtifactStatus.FAILED
    assert await spent_today(core, student) == (
        expected_first.weighted + expected_second.weighted
    )
    assert artifact.weighted == (expected_first + expected_second).weighted
    assert (artifact.tokens_in, artifact.tokens_out) == (1800, 150)
    assert artifact.tokens_cached == 500
    assert artifact.cost_micro == 2000


# - - - Thin sources - - -


async def test_thin_sources_get_the_teaching_note(
    studio: StudioServices,
    student: Actor,
    notebook: Notebook,
    source: Source,
    uow_factory: UowFactory,
    scripted_llm: HookedLlm,
) -> None:
    """A pack under 1 500 tokens tells the model to teach the whole topic."""
    await generate(
        studio, uow_factory, student, notebook, ArtifactKind.REPORT, CONSPECT
    )

    task = scripted_llm.json_requests[0]["messages"][1]["content"]
    assert "The sources are short (" in task and "words in all:" in task
    assert f"«{source.title}»" in task
    assert 'items from your own knowledge leave "refs" empty' in task


async def test_big_sources_get_no_thin_note(
    build: Build,
    student: Actor,
    notebook: Notebook,
    uow_factory: UowFactory,
    scripted_llm: HookedLlm,
) -> None:
    """About 3 000 tokens of text is not thin."""
    await make_source(uow_factory, notebook, texts=big_texts(), title="Big")
    studio = build()

    await generate(
        studio, uow_factory, student, notebook, ArtifactKind.REPORT, CONSPECT
    )

    task = scripted_llm.json_requests[0]["messages"][1]["content"]
    assert "The sources are short" not in task
