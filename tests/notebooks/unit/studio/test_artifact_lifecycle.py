"""NB-9, NB-14: list, open, rename, cancel, delete and retry Studio outputs."""

from datetime import timedelta
from uuid import UUID

from app.modules.notebooks.domain.entities import Notebook, Source
from app.modules.notebooks.domain.enums import ArtifactKind, ArtifactStatus
from app.modules.notebooks.domain.errors import (
    ArtifactNotReadyError,
    InvalidOptionsError,
    LimitReachedError,
    NotebookNotFoundError,
)
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.modules.notebooks.wiring_core import NotebooksCore
from app.modules.notebooks.wiring_studio import StudioServices
from app.shared.actor import Actor
from app.shared.contracts.ai import AiProviderError
from app.shared.notifications import NotificationDraft
from tests.factories.notebooks import NOW, make_artifact, make_notebook
from tests.fakes.clock import FixedClock
from tests.fakes.tasks import FakeTaskKicker
from tests.notebooks.unit.studio.helpers import HookedLlm, generate, stored

import pytest


async def used_today(core: NotebooksCore, actor: Actor) -> int:
    """How many outputs were requested today (the `artifacts` counter)."""
    return (await core.quota.snapshot(actor.user_id))["artifacts"].used


# - - - List and open - - -


async def test_list_returns_newest_first_without_content_and_filters(
    studio: StudioServices,
    student: Actor,
    notebook: Notebook,
    uow_factory: UowFactory,
) -> None:
    """NB-9: newest first, no content, filters by kind and status, no deleted ones."""
    report = await make_artifact(uow_factory, notebook, created_at=NOW)
    quiz = await make_artifact(
        uow_factory,
        notebook,
        ArtifactKind.QUIZ,
        ArtifactStatus.FAILED,
        created_at=NOW + timedelta(minutes=1),
    )
    cards = await make_artifact(
        uow_factory,
        notebook,
        ArtifactKind.FLASHCARDS,
        ArtifactStatus.GENERATING,
        created_at=NOW + timedelta(minutes=2),
    )
    await make_artifact(
        uow_factory,
        notebook,
        created_at=NOW + timedelta(minutes=3),
        deleted_at=NOW,
    )

    everything = await studio.list_artifacts.execute(student, notebook.id)
    quizzes = await studio.list_artifacts.execute(
        student, notebook.id, kind=ArtifactKind.QUIZ
    )
    ready = await studio.list_artifacts.execute(
        student, notebook.id, status=ArtifactStatus.READY
    )

    assert [a.id for a in everything] == [cards.id, quiz.id, report.id]
    assert all(a.content is None for a in everything)
    assert [a.id for a in quizzes] == [quiz.id]
    assert [a.id for a in ready] == [report.id]


async def test_open_sets_viewed_at_once_and_returns_the_progress(
    studio: StudioServices,
    student: Actor,
    notebook: Notebook,
    uow_factory: UowFactory,
    clock: FixedClock,
) -> None:
    """NB-9, NB-10: the first view of a ready output clears the blue dot."""
    artifact = await make_artifact(uow_factory, notebook, ArtifactKind.FLASHCARDS)
    assert artifact.unread

    first = await studio.get_artifact.execute(student, notebook.id, artifact.id)
    clock.advance(minutes=5)
    await studio.save_progress.execute(
        student, notebook.id, artifact.id, {"known": ["c1"], "position": 2}
    )
    second = await studio.get_artifact.execute(student, notebook.id, artifact.id)

    assert first.artifact.content == artifact.content
    assert first.artifact.viewed_at == NOW
    assert not first.artifact.unread
    assert first.progress_state is None
    assert second.artifact.viewed_at == NOW
    assert second.progress_state == {"known": ["c1"], "position": 2}


async def test_open_does_not_mark_an_unfinished_output_as_viewed(
    studio: StudioServices,
    student: Actor,
    notebook: Notebook,
    uow_factory: UowFactory,
) -> None:
    """NB-9: only a ready output can be viewed."""
    artifact = await make_artifact(
        uow_factory, notebook, ArtifactKind.QUIZ, ArtifactStatus.GENERATING
    )

    opened = await studio.get_artifact.execute(student, notebook.id, artifact.id)

    assert opened.artifact.viewed_at is None
    assert (await stored(uow_factory, artifact.id)).viewed_at is None


# - - - Rename - - -


async def test_rename_trims_the_title(
    studio: StudioServices,
    student: Actor,
    notebook: Notebook,
    uow_factory: UowFactory,
) -> None:
    """NB-9: outputs can be renamed."""
    artifact = await make_artifact(uow_factory, notebook)

    renamed = await studio.rename_artifact.execute(
        student, notebook.id, artifact.id, "  My   conspect \n"
    )

    assert renamed.title == "My conspect"
    assert (await stored(uow_factory, artifact.id)).title == "My conspect"


@pytest.mark.parametrize("title", ["", "   ", "x" * 201])
async def test_rename_needs_a_title_of_1_to_200_characters(
    studio: StudioServices,
    student: Actor,
    notebook: Notebook,
    uow_factory: UowFactory,
    title: str,
) -> None:
    """NB-9: an empty or too long title is refused and the old one stays."""
    artifact = await make_artifact(uow_factory, notebook, title="Old")

    with pytest.raises(InvalidOptionsError):
        await studio.rename_artifact.execute(student, notebook.id, artifact.id, title)

    assert (await stored(uow_factory, artifact.id)).title == "Old"


# - - - Delete and cancel - - -


async def test_delete_hides_a_ready_output(
    studio: StudioServices,
    student: Actor,
    notebook: Notebook,
    uow_factory: UowFactory,
) -> None:
    """NB-9: delete is a soft delete; the output disappears from list and open."""
    artifact = await make_artifact(uow_factory, notebook)

    await studio.delete_artifact.execute(student, notebook.id, artifact.id)

    assert (await stored(uow_factory, artifact.id)).deleted_at is not None
    assert await studio.list_artifacts.execute(student, notebook.id) == []
    with pytest.raises(NotebookNotFoundError):
        await studio.get_artifact.execute(student, notebook.id, artifact.id)


async def test_delete_cancels_a_queued_output(
    studio: StudioServices,
    core: NotebooksCore,
    student: Actor,
    notebook: Notebook,
    source: Source,
    uow_factory: UowFactory,
    scripted_llm: HookedLlm,
) -> None:
    """NB-9: deleting an output that waits for its job cancels it; the job skips it."""
    queued = await studio.request_artifact.execute(
        student, notebook.id, ArtifactKind.QUIZ, {}, None
    )

    await studio.delete_artifact.execute(student, notebook.id, queued.id)
    await studio.generate_artifact.execute(queued.id)

    row = await stored(uow_factory, queued.id)
    assert row.status is ArtifactStatus.CANCELED
    assert row.deleted_at is not None
    assert scripted_llm.calls == 0
    assert await core.quota.running_count(student.user_id) == 0


async def test_cancel_stops_a_queued_output_and_gives_the_count_back(
    studio: StudioServices,
    core: NotebooksCore,
    student: Actor,
    notebook: Notebook,
    source: Source,
    uow_factory: UowFactory,
    scripted_llm: HookedLlm,
    clock: FixedClock,
) -> None:
    """NB-9, NB-14: cancel frees the slot and the daily count; the job does nothing."""
    queued = await studio.request_artifact.execute(
        student, notebook.id, ArtifactKind.QUIZ, {}, None
    )

    canceled = await studio.cancel_artifact.execute(student, notebook.id, queued.id)
    await studio.generate_artifact.execute(queued.id)

    row = await stored(uow_factory, queued.id)
    assert canceled.status is ArtifactStatus.CANCELED
    assert row.status is ArtifactStatus.CANCELED
    assert row.error is not None
    assert row.error.code == "canceled"
    assert row.error.message_key == "notebooks-artifact-error-canceled"
    assert row.finished_at == clock.now()
    assert scripted_llm.calls == 0
    assert await used_today(core, student) == 0
    assert await core.quota.running_count(student.user_id) == 0


@pytest.mark.parametrize(
    "status", [ArtifactStatus.READY, ArtifactStatus.FAILED, ArtifactStatus.CANCELED]
)
async def test_only_queued_or_generating_outputs_can_be_canceled(
    studio: StudioServices,
    student: Actor,
    notebook: Notebook,
    uow_factory: UowFactory,
    status: ArtifactStatus,
) -> None:
    """NB-9: other statuses answer 409 artifact-not-ready."""
    artifact = await make_artifact(uow_factory, notebook, status=status)

    with pytest.raises(ArtifactNotReadyError):
        await studio.cancel_artifact.execute(student, notebook.id, artifact.id)


# - - - Interrupted jobs - - -


async def test_cancel_during_generation_discards_the_result(
    studio: StudioServices,
    core: NotebooksCore,
    student: Actor,
    notebook: Notebook,
    source: Source,
    uow_factory: UowFactory,
    scripted_llm: HookedLlm,
    outbox: list[NotificationDraft],
) -> None:
    """NB-9: the student cancels while the model works; the document is thrown away."""
    queued = await studio.request_artifact.execute(
        student, notebook.id, ArtifactKind.QUIZ, {}, None
    )

    async def cancel() -> None:
        await studio.cancel_artifact.execute(student, notebook.id, queued.id)

    scripted_llm.before_json = cancel

    await studio.generate_artifact.execute(queued.id)

    row = await stored(uow_factory, queued.id)
    assert row.status is ArtifactStatus.CANCELED
    assert row.content is None
    assert row.refs_index is None
    assert outbox == []
    assert scripted_llm.calls == 1
    assert (await core.budget.usage(student.user_id)).day.used > 0  # it was spent
    assert await used_today(core, student) == 0
    assert await core.quota.running_count(student.user_id) == 0


async def test_delete_during_generation_discards_the_result(
    studio: StudioServices,
    student: Actor,
    notebook: Notebook,
    source: Source,
    uow_factory: UowFactory,
    scripted_llm: HookedLlm,
    outbox: list[NotificationDraft],
) -> None:
    """NB-9: deleting a generating output cancels it and hides it."""
    queued = await studio.request_artifact.execute(
        student, notebook.id, ArtifactKind.QUIZ, {}, None
    )

    async def delete() -> None:
        await studio.delete_artifact.execute(student, notebook.id, queued.id)

    scripted_llm.before_json = delete

    await studio.generate_artifact.execute(queued.id)

    row = await stored(uow_factory, queued.id)
    assert row.status is ArtifactStatus.CANCELED
    assert row.deleted_at is not None
    assert row.content is None
    assert outbox == []


async def test_rename_during_generation_wins_over_the_title_of_the_model(
    studio: StudioServices,
    student: Actor,
    notebook: Notebook,
    source: Source,
    uow_factory: UowFactory,
    scripted_llm: HookedLlm,
) -> None:
    """NB-9: a title typed by the student is not overwritten by the model's."""
    queued = await studio.request_artifact.execute(
        student, notebook.id, ArtifactKind.QUIZ, {}, None
    )

    async def rename() -> None:
        scripted_llm.before_json = None
        await studio.rename_artifact.execute(
            student, notebook.id, queued.id, "My own title"
        )

    scripted_llm.before_json = rename

    await studio.generate_artifact.execute(queued.id)

    row = await stored(uow_factory, queued.id)
    assert row.status is ArtifactStatus.READY
    assert row.title == "My own title"


async def test_retry_while_the_old_job_runs_drops_the_old_result(
    studio: StudioServices,
    core: NotebooksCore,
    student: Actor,
    notebook: Notebook,
    source: Source,
    uow_factory: UowFactory,
    scripted_llm: HookedLlm,
) -> None:
    """NB-9: cancel + retry during a run: only the new run writes the result."""
    queued = await studio.request_artifact.execute(
        student, notebook.id, ArtifactKind.QUIZ, {}, None
    )

    async def cancel_and_retry() -> None:
        scripted_llm.before_json = None
        await studio.cancel_artifact.execute(student, notebook.id, queued.id)
        await studio.retry_artifact.execute(student, notebook.id, queued.id)

    scripted_llm.before_json = cancel_and_retry

    await studio.generate_artifact.execute(queued.id)

    after_old = await stored(uow_factory, queued.id)
    assert after_old.status is ArtifactStatus.QUEUED
    assert after_old.content is None
    assert await core.quota.running_count(student.user_id) == 1

    await studio.generate_artifact.execute(queued.id)

    after_new = await stored(uow_factory, queued.id)
    assert after_new.status is ArtifactStatus.READY
    assert after_new.attempts == 2
    assert await core.quota.running_count(student.user_id) == 0
    assert await used_today(core, student) == 1


# - - - Retry - - -


async def test_retry_runs_a_failed_output_again(
    studio: StudioServices,
    core: NotebooksCore,
    student: Actor,
    notebook: Notebook,
    source: Source,
    uow_factory: UowFactory,
    scripted_llm: HookedLlm,
    kicker: FakeTaskKicker,
) -> None:
    """NB-9: a failed output goes back to `queued` and is generated again."""
    for _ in range(3):
        scripted_llm.queue_error(AiProviderError())
    failed = await generate(
        studio, uow_factory, student, notebook, ArtifactKind.QUIZ, {}
    )
    assert failed.status is ArtifactStatus.FAILED

    retried = await studio.retry_artifact.execute(student, notebook.id, failed.id)

    row = await stored(uow_factory, failed.id)
    assert retried.status is ArtifactStatus.QUEUED
    assert (row.status, row.error, row.content, row.finished_at) == (
        ArtifactStatus.QUEUED,
        None,
        None,
        None,
    )
    assert kicker.names().count("notebooks.generate_artifact") == 2
    assert await used_today(core, student) == 1

    await studio.generate_artifact.execute(failed.id)

    done = await stored(uow_factory, failed.id)
    assert done.status is ArtifactStatus.READY
    assert done.content is not None
    assert done.attempts == 2
    assert await used_today(core, student) == 1


async def test_retry_brings_a_canceled_output_back(
    studio: StudioServices,
    student: Actor,
    notebook: Notebook,
    source: Source,
) -> None:
    """NB-9: a canceled output can be retried too."""
    queued = await studio.request_artifact.execute(
        student, notebook.id, ArtifactKind.MIND_MAP, {}, None
    )
    await studio.cancel_artifact.execute(student, notebook.id, queued.id)

    retried = await studio.retry_artifact.execute(student, notebook.id, queued.id)

    assert retried.status is ArtifactStatus.QUEUED
    assert retried.error is None


@pytest.mark.parametrize(
    "status", [ArtifactStatus.READY, ArtifactStatus.QUEUED, ArtifactStatus.GENERATING]
)
async def test_only_failed_or_canceled_outputs_can_be_retried(
    studio: StudioServices,
    student: Actor,
    notebook: Notebook,
    uow_factory: UowFactory,
    status: ArtifactStatus,
) -> None:
    """NB-9: other statuses answer 409 artifact-not-ready."""
    artifact = await make_artifact(uow_factory, notebook, status=status)

    with pytest.raises(ArtifactNotReadyError):
        await studio.retry_artifact.execute(student, notebook.id, artifact.id)


async def test_retry_is_refused_when_the_budget_is_used_up(
    studio: StudioServices,
    core: NotebooksCore,
    student: Actor,
    notebook: Notebook,
    source: Source,
    uow_factory: UowFactory,
) -> None:
    """NB-14: a retry is a new run: it needs budget and stays failed without it."""
    queued = await studio.request_artifact.execute(
        student, notebook.id, ArtifactKind.QUIZ, {}, None
    )
    await studio.cancel_artifact.execute(student, notebook.id, queued.id)
    await core.budget.add(student.user_id, 4_000_000)

    with pytest.raises(LimitReachedError):
        await studio.retry_artifact.execute(student, notebook.id, queued.id)

    assert (await stored(uow_factory, queued.id)).status is ArtifactStatus.CANCELED
    assert await used_today(core, student) == 0


# - - - Access - - -


async def test_every_action_answers_404_for_another_students_output(
    studio: StudioServices,
    other_student: Actor,
    notebook: Notebook,
    uow_factory: UowFactory,
) -> None:
    """NB-15: outputs of someone else's notebook are not found, whatever the action."""
    artifact = await make_artifact(uow_factory, notebook)
    nb, aid = notebook.id, artifact.id
    calls = [
        studio.list_artifacts.execute(other_student, nb),
        studio.get_artifact.execute(other_student, nb, aid),
        studio.rename_artifact.execute(other_student, nb, aid, "Mine"),
        studio.delete_artifact.execute(other_student, nb, aid),
        studio.cancel_artifact.execute(other_student, nb, aid),
        studio.retry_artifact.execute(other_student, nb, aid),
        studio.save_progress.execute(other_student, nb, aid, {}),
        studio.save_as_source.execute(other_student, nb, aid),
        studio.save_flashcard_set.execute(other_student, nb, aid),
        studio.edit_slides.execute(other_student, nb, aid, []),
        studio.revise_slides.execute(other_student, nb, aid, []),
    ]

    for call in calls:
        with pytest.raises(NotebookNotFoundError):
            await call

    assert (await stored(uow_factory, aid)).deleted_at is None


async def test_output_of_another_notebook_is_not_found(
    studio: StudioServices,
    student: Actor,
    notebook: Notebook,
    uow_factory: UowFactory,
) -> None:
    """NB-15: an output is reachable only through the notebook it belongs to."""
    elsewhere = await make_notebook(uow_factory, student.user_id, title="Chemistry")
    artifact = await make_artifact(uow_factory, notebook)
    missing = UUID(int=1)

    with pytest.raises(NotebookNotFoundError):
        await studio.get_artifact.execute(student, elsewhere.id, artifact.id)
    with pytest.raises(NotebookNotFoundError):
        await studio.get_artifact.execute(student, notebook.id, missing)
