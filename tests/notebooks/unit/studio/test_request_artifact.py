"""NB-8, NB-9, NB-14: asking for a Studio output (validation, limits, the queue)."""

from typing import Any

from app.modules.notebooks.domain.entities import Notebook, Source
from app.modules.notebooks.domain.enums import (
    ArtifactKind,
    ArtifactStatus,
    SourceStatus,
)
from app.modules.notebooks.domain.errors import (
    ArtifactLimitError,
    BusyError,
    FeatureDisabledError,
    InvalidOptionsError,
    LimitReachedError,
    NoSourcesSelectedError,
    NotebookNotFoundError,
    QuotaExceededError,
)
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.modules.notebooks.wiring_core import NotebooksCore
from app.modules.notebooks.wiring_studio import StudioServices
from app.shared.actor import Actor
from tests.factories.notebooks import make_source
from tests.fakes.clock import FixedClock
from tests.fakes.tasks import FakeTaskKicker
from tests.notebooks.unit.studio.helpers import (
    SOURCE_TEXTS,
    Build,
    HookedLlm,
    generate,
    stored,
)

import pytest

CONSPECT = {"format": "conspect"}


async def used_today(core: NotebooksCore, actor: Actor, counter: str) -> int:
    """How many outputs of a counter (`artifacts`, `slides`, ...) were requested."""
    return (await core.quota.snapshot(actor.user_id))[counter].used


async def test_request_queues_the_output_and_starts_the_job(
    studio: StudioServices,
    core: NotebooksCore,
    student: Actor,
    notebook: Notebook,
    source: Source,
    uow_factory: UowFactory,
    kicker: FakeTaskKicker,
) -> None:
    """NB-9: a request answers at once with a queued row and kicks the job."""
    artifact = await studio.request_artifact.execute(
        student, notebook.id, ArtifactKind.REPORT, CONSPECT, None
    )

    row = await stored(uow_factory, artifact.id)
    assert row.status is ArtifactStatus.QUEUED
    assert (row.kind, row.format) == (ArtifactKind.REPORT, "conspect")
    assert row.title == "Conspect: Biology"
    assert row.options["detail"] == "standard"
    assert row.options["style"] == "outline"
    assert row.source_ids == [source.id]
    assert row.source_map == {"S1": str(source.id)}
    assert row.content is None
    assert kicker.calls == [
        ("notebooks.generate_artifact", {"artifact_id": str(artifact.id)})
    ]
    assert await used_today(core, student, "artifacts") == 1
    assert await core.quota.running_count(student.user_id) == 1


async def test_request_keeps_the_focus_text_and_the_chosen_sources(
    studio: StudioServices,
    student: Actor,
    notebook: Notebook,
    source: Source,
    uow_factory: UowFactory,
) -> None:
    """NB-8: `source_ids` win over the selection; the focus text is trimmed."""
    second = await make_source(uow_factory, notebook, texts=SOURCE_TEXTS, title="Two")
    options = {"source_ids": [str(second.id)]}

    artifact = await studio.request_artifact.execute(
        student, notebook.id, ArtifactKind.QUIZ, options, "  Only the Calvin cycle  "
    )

    assert artifact.prompt == "Only the Calvin cycle"
    assert artifact.source_ids == [second.id]
    assert artifact.source_map == {"S1": str(second.id)}


async def test_request_without_source_ids_uses_the_selection_in_position_order(
    studio: StudioServices,
    student: Actor,
    notebook: Notebook,
    uow_factory: UowFactory,
) -> None:
    """NB-5: the selected, ready sources are numbered S1.. by position."""
    first = await make_source(uow_factory, notebook, texts=SOURCE_TEXTS, title="A")
    await make_source(
        uow_factory, notebook, texts=SOURCE_TEXTS, title="B", selected=False
    )
    third = await make_source(uow_factory, notebook, texts=SOURCE_TEXTS, title="C")

    artifact = await studio.request_artifact.execute(
        student, notebook.id, ArtifactKind.MIND_MAP, {}, None
    )

    assert artifact.source_ids == [first.id, third.id]
    assert artifact.source_map == {"S1": str(first.id), "S2": str(third.id)}


async def test_request_without_a_selected_source_is_made_without_sources(
    studio: StudioServices,
    core: NotebooksCore,
    student: Actor,
    notebook: Notebook,
    uow_factory: UowFactory,
    kicker: FakeTaskKicker,
) -> None:
    """T6.3: a ready source that is not checked is left out; the output is general."""
    await make_source(uow_factory, notebook, texts=SOURCE_TEXTS, selected=False)

    artifact = await studio.request_artifact.execute(
        student, notebook.id, ArtifactKind.QUIZ, {}, None
    )

    assert artifact.source_ids == [] and artifact.cache_key is None
    assert artifact.status is ArtifactStatus.QUEUED
    assert kicker.calls != []
    assert await used_today(core, student, "artifacts") == 1


async def test_request_needs_a_ready_source(
    studio: StudioServices,
    student: Actor,
    notebook: Notebook,
    uow_factory: UowFactory,
) -> None:
    """NB-5: a source that is still processing cannot feed an output."""
    await make_source(uow_factory, notebook, texts=(), status=SourceStatus.PROCESSING)

    with pytest.raises(NoSourcesSelectedError):
        await studio.request_artifact.execute(
            student, notebook.id, ArtifactKind.QUIZ, {}, None
        )


async def test_audio_overview_is_not_available(
    studio: StudioServices, student: Actor, notebook: Notebook, source: Source
) -> None:
    """No audio overview, by decision: the feature is switched off."""
    with pytest.raises(FeatureDisabledError):
        await studio.request_artifact.execute(
            student, notebook.id, ArtifactKind.AUDIO_OVERVIEW, {}, None
        )


async def test_unknown_kind_is_invalid_options(
    studio: StudioServices, student: Actor, notebook: Notebook, source: Source
) -> None:
    """NB-20: a kind that does not exist is a validation error."""
    with pytest.raises(InvalidOptionsError):
        await studio.request_artifact.execute(student, notebook.id, "podcast", {}, None)


@pytest.mark.parametrize(
    ("kind", "options"),
    [
        (ArtifactKind.REPORT, {}),
        (ArtifactKind.REPORT, {"format": "poem"}),
        (ArtifactKind.QUIZ, {"count": "plenty"}),
        (ArtifactKind.FLASHCARDS, {"difficulty": "impossible"}),
    ],
)
async def test_options_must_match_the_kind(
    studio: StudioServices,
    core: NotebooksCore,
    student: Actor,
    notebook: Notebook,
    source: Source,
    kind: ArtifactKind,
    options: dict[str, Any],
) -> None:
    """NB-20: wrong options are refused before anything is counted."""
    with pytest.raises(InvalidOptionsError):
        await studio.request_artifact.execute(student, notebook.id, kind, options, None)

    assert await used_today(core, student, "artifacts") == 0


async def test_custom_report_needs_the_prompt(
    studio: StudioServices, student: Actor, notebook: Notebook, source: Source
) -> None:
    """NB-8: a custom report without a task is rejected at once, with one is queued."""
    with pytest.raises(InvalidOptionsError):
        await studio.request_artifact.execute(
            student, notebook.id, ArtifactKind.REPORT, {"format": "custom"}, None
        )

    artifact = await studio.request_artifact.execute(
        student,
        notebook.id,
        ArtifactKind.REPORT,
        {"format": "custom"},
        "Compare the two stages",
    )

    assert artifact.format == "custom"


async def test_focus_text_over_1000_characters_is_refused(
    studio: StudioServices, student: Actor, notebook: Notebook, source: Source
) -> None:
    """NB-8: the focus text is at most 1 000 characters."""
    with pytest.raises(InvalidOptionsError):
        await studio.request_artifact.execute(
            student, notebook.id, ArtifactKind.MIND_MAP, {}, "x" * 1001
        )


async def test_another_students_notebook_is_not_found(
    studio: StudioServices,
    other_student: Actor,
    notebook: Notebook,
    source: Source,
    kicker: FakeTaskKicker,
) -> None:
    """NB-15: the notebook of someone else answers 404 and starts nothing."""
    with pytest.raises(NotebookNotFoundError):
        await studio.request_artifact.execute(
            other_student, notebook.id, ArtifactKind.QUIZ, {}, None
        )

    assert kicker.calls == []


async def test_notebook_keeps_at_most_max_artifacts(
    build: Build,
    core: NotebooksCore,
    student: Actor,
    notebook: Notebook,
    source: Source,
) -> None:
    """NB-8: the 61st output (here the 2nd, with a limit of 1) is refused."""
    studio = build(notebooks={"max_artifacts": 1})
    await studio.request_artifact.execute(
        student, notebook.id, ArtifactKind.QUIZ, {}, None
    )

    with pytest.raises(ArtifactLimitError):
        await studio.request_artifact.execute(
            student, notebook.id, ArtifactKind.QUIZ, {}, None
        )

    assert await used_today(core, student, "artifacts") == 1


async def test_fourth_running_output_is_busy(
    studio: StudioServices,
    core: NotebooksCore,
    student: Actor,
    notebook: Notebook,
    source: Source,
    uow_factory: UowFactory,
    kicker: FakeTaskKicker,
) -> None:
    """NB-14: at most three outputs are queued or generating at once."""
    for _ in range(3):
        await studio.request_artifact.execute(
            student, notebook.id, ArtifactKind.MIND_MAP, {}, None
        )

    with pytest.raises(BusyError):
        await studio.request_artifact.execute(
            student, notebook.id, ArtifactKind.MIND_MAP, {}, None
        )

    assert len(await studio.list_artifacts.execute(student, notebook.id)) == 3
    assert len(kicker.calls) == 3
    assert await used_today(core, student, "artifacts") == 3


async def test_21st_request_of_the_day_exceeds_the_quota(
    studio: StudioServices,
    student: Actor,
    notebook: Notebook,
    source: Source,
    uow_factory: UowFactory,
) -> None:
    """NB-14: 20 outputs a day; the 21st answers 429 with the limit.

    Each request has its own focus text: a request that repeats an earlier one is
    served from the shared cache and generates nothing.
    """
    for n in range(20):
        await generate(
            studio,
            uow_factory,
            student,
            notebook,
            ArtifactKind.MIND_MAP,
            {},
            prompt=f"focus {n}",
        )

    with pytest.raises(QuotaExceededError) as caught:
        await studio.request_artifact.execute(
            student, notebook.id, ArtifactKind.MIND_MAP, {}, "one more focus"
        )

    assert caught.value.params["limit"] == 20
    assert caught.value.params["kind"] == "artifacts"


async def test_slides_have_their_own_daily_count(
    build: Build,
    student: Actor,
    notebook: Notebook,
    source: Source,
    uow_factory: UowFactory,
) -> None:
    """NB-14: slides are limited separately; other kinds are not affected."""
    studio = build(limits={"nb_slides_per_day": 1})
    await generate(
        studio, uow_factory, student, notebook, ArtifactKind.SLIDES, {}, prompt="a"
    )

    with pytest.raises(QuotaExceededError) as caught:
        await studio.request_artifact.execute(
            student, notebook.id, ArtifactKind.SLIDES, {}, "b"
        )
    await studio.request_artifact.execute(
        student, notebook.id, ArtifactKind.QUIZ, {}, "c"
    )

    assert caught.value.params["kind"] == "slides"


async def test_daily_counts_restart_at_tashkent_midnight(
    build: Build,
    student: Actor,
    notebook: Notebook,
    source: Source,
    uow_factory: UowFactory,
    clock: FixedClock,
) -> None:
    """NB-14: the counters reset with the Tashkent day (FixedClock)."""
    studio = build(limits={"nb_artifacts_per_day": 1})
    await generate(
        studio, uow_factory, student, notebook, ArtifactKind.QUIZ, {}, prompt="a"
    )
    with pytest.raises(QuotaExceededError):
        await studio.request_artifact.execute(
            student, notebook.id, ArtifactKind.QUIZ, {}, "b"
        )

    clock.advance(hours=12)  # 09:00 UTC is 14:00 in Tashkent; now it is 02:00 next day

    artifact = await studio.request_artifact.execute(
        student, notebook.id, ArtifactKind.QUIZ, {}, "b"
    )
    assert artifact.status is ArtifactStatus.QUEUED


async def test_request_over_the_budget_is_refused_before_any_call(
    studio: StudioServices,
    core: NotebooksCore,
    student: Actor,
    notebook: Notebook,
    source: Source,
    scripted_llm: HookedLlm,
    kicker: FakeTaskKicker,
) -> None:
    """NB-14: no budget left means 429 limit-reached; nothing is queued or counted."""
    await core.budget.add(student.user_id, 4_000_000)

    with pytest.raises(LimitReachedError) as caught:
        await studio.request_artifact.execute(
            student, notebook.id, ArtifactKind.QUIZ, {}, None
        )

    assert caught.value.params["scope"] == "day"
    assert scripted_llm.calls == 0
    assert kicker.calls == []
    assert await used_today(core, student, "artifacts") == 0
    assert await core.quota.running_count(student.user_id) == 0
