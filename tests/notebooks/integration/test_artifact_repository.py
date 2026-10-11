"""NB-8: Studio outputs, progress and files of an output in PostgreSQL."""

from datetime import timedelta
from uuid import UUID

from app.modules.notebooks.domain.entities import (
    ArtifactError,
    ArtifactProgress,
    Notebook,
)
from app.modules.notebooks.domain.enums import ArtifactKind, ArtifactStatus
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from app.shared.ids import new_id
from tests.factories.notebooks import (
    NOW,
    make_artifact,
    make_notebook,
    new_artifact_entity,
)

import pytest


@pytest.fixture
async def notebook(uow_factory: UowFactory, student: Actor) -> Notebook:
    """A stored notebook of the student."""
    return await make_notebook(uow_factory, student.user_id)


async def test_add_then_get_returns_every_stored_field(
    uow_factory: UowFactory, notebook: Notebook
) -> None:
    """NB-8: jsonb, uuid[] and the error payload of an output round-trip."""
    first, second = new_id(), new_id()
    artifact = new_artifact_entity(
        notebook,
        kind=ArtifactKind.SLIDES,
        format="deck",
        title="Slides",
        status=ArtifactStatus.FAILED,
        error=ArtifactError(
            code="invalid_output",
            message_key="notebooks-artifact-invalid",
            params={"attempts": 2},
        ),
        options={"slides": 8, "style": "plain"},
        prompt="Focus on light",
        source_ids=[first, second],
        source_map={"S1": str(first), "S2": str(second)},
        sampled=True,
        content={"slides": [{"title": "Light"}]},
        refs_index={"S1:P1": {"source_id": str(first)}},
        model="anthropic/claude-haiku-5.5",
        tokens_in=1000,
        tokens_out=2000,
        tokens_cached=500,
        weighted=11_000,
        cost_micro=12_345_678_901,
        attempts=2,
        progress=40,
        parent_id=new_id(),
        flashcard_set_id=new_id(),
        started_at=NOW,
        finished_at=NOW + timedelta(seconds=30),
        viewed_at=NOW + timedelta(minutes=1),
        deleted_at=NOW + timedelta(minutes=2),
    )

    async with uow_factory() as uow:
        await uow.artifacts.add(artifact)
        await uow.commit()
    async with uow_factory() as uow:
        loaded = await uow.artifacts.get(artifact.id)
        locked = await uow.artifacts.get_for_update(artifact.id)
        missing = await uow.artifacts.get(new_id())

    assert loaded == artifact
    assert locked == artifact
    assert missing is None


async def test_save_writes_the_result_of_a_run(
    uow_factory: UowFactory, notebook: Notebook
) -> None:
    """NB-8: the worker stores status, content and usage on the same row."""
    artifact = await make_artifact(
        uow_factory, notebook, status=ArtifactStatus.GENERATING
    )
    artifact.status = ArtifactStatus.READY
    artifact.content = {"markdown": "# Done"}
    artifact.tokens_in, artifact.tokens_out = 10, 20
    artifact.attempts = 1
    artifact.finished_at = NOW + timedelta(seconds=9)
    artifact.updated_at = NOW + timedelta(seconds=9)

    async with uow_factory() as uow:
        await uow.artifacts.save(artifact)
        await uow.artifacts.save(new_artifact_entity(notebook))
        await uow.commit()
    async with uow_factory() as uow:
        loaded = await uow.artifacts.get(artifact.id)

    assert loaded == artifact


async def test_list_returns_live_outputs_newest_first_without_content(
    uow_factory: UowFactory, student: Actor, notebook: Notebook
) -> None:
    """NB-8: the Studio list hides deleted outputs and leaves out the heavy content."""
    other = await make_notebook(uow_factory, student.user_id)
    oldest = await make_artifact(
        uow_factory, notebook, created_at=NOW, kind=ArtifactKind.QUIZ
    )
    newest = await make_artifact(
        uow_factory, notebook, created_at=NOW + timedelta(hours=2)
    )
    middle = await make_artifact(
        uow_factory,
        notebook,
        created_at=NOW + timedelta(hours=1),
        status=ArtifactStatus.QUEUED,
    )
    await make_artifact(uow_factory, notebook, deleted_at=NOW)
    await make_artifact(uow_factory, other)

    async with uow_factory() as uow:
        everything = await uow.artifacts.list_for_notebook(
            notebook.id, kind=None, status=None
        )
        quizzes = await uow.artifacts.list_for_notebook(
            notebook.id, kind=ArtifactKind.QUIZ, status=None
        )
        queued = await uow.artifacts.list_for_notebook(
            notebook.id, kind=None, status=ArtifactStatus.QUEUED
        )
        none = await uow.artifacts.list_for_notebook(
            notebook.id, kind=ArtifactKind.QUIZ, status=ArtifactStatus.QUEUED
        )

    assert [a.id for a in everything] == [newest.id, middle.id, oldest.id]
    assert [a.id for a in quizzes] == [oldest.id]
    assert [a.id for a in queued] == [middle.id]
    assert none == []
    assert all(a.content is None for a in everything)
    assert newest.content is not None


async def test_get_after_a_list_still_returns_the_content(
    uow_factory: UowFactory, notebook: Notebook
) -> None:
    """NB-8: listing without content does not spoil a later read in the session."""
    artifact = await make_artifact(uow_factory, notebook)

    async with uow_factory() as uow:
        await uow.artifacts.list_for_notebook(notebook.id, kind=None, status=None)
        loaded = await uow.artifacts.get(artifact.id)

    assert loaded is not None and loaded.content == artifact.content


async def test_count_live_skips_deleted_outputs(
    uow_factory: UowFactory, student: Actor, notebook: Notebook
) -> None:
    """NB-8: the per-notebook limit counts the outputs that are not deleted."""
    other = await make_notebook(uow_factory, student.user_id)
    await make_artifact(uow_factory, notebook)
    await make_artifact(uow_factory, notebook, status=ArtifactStatus.FAILED)
    await make_artifact(uow_factory, notebook, deleted_at=NOW)
    await make_artifact(uow_factory, other)

    async with uow_factory() as uow:
        assert await uow.artifacts.count_live(notebook.id) == 2
        assert await uow.artifacts.count_live(new_id()) == 0


async def test_stuck_generating_returns_old_runs_oldest_first(
    uow_factory: UowFactory, notebook: Notebook
) -> None:
    """NB-8: a run that started before the cutoff and never finished is found."""
    cutoff = NOW
    oldest = await make_artifact(
        uow_factory,
        notebook,
        status=ArtifactStatus.GENERATING,
        started_at=cutoff - timedelta(hours=2),
    )
    older = await make_artifact(
        uow_factory,
        notebook,
        status=ArtifactStatus.GENERATING,
        started_at=cutoff - timedelta(minutes=30),
    )
    await make_artifact(
        uow_factory,
        notebook,
        status=ArtifactStatus.GENERATING,
        started_at=cutoff + timedelta(minutes=1),
    )
    await make_artifact(
        uow_factory,
        notebook,
        status=ArtifactStatus.READY,
        started_at=cutoff - timedelta(hours=3),
    )
    await make_artifact(uow_factory, notebook, status=ArtifactStatus.QUEUED)

    async with uow_factory() as uow:
        stuck = await uow.artifacts.stuck_generating(cutoff, limit=10)
        limited = await uow.artifacts.stuck_generating(cutoff, limit=1)

    assert [a.id for a in stuck] == [oldest.id, older.id]
    assert [a.id for a in limited] == [oldest.id]
    assert all(a.content is None for a in stuck)


# - - - progress - - -


async def test_progress_is_inserted_then_replaced_per_student(
    uow_factory: UowFactory, notebook: Notebook
) -> None:
    """NB-8: resume where the student left; upsert keeps one row per student."""
    artifact = await make_artifact(uow_factory, notebook, ArtifactKind.FLASHCARDS)
    me, other = notebook.owner_id, new_id()

    def progress(
        user: UUID, state: dict[str, object], minutes: int
    ) -> ArtifactProgress:
        return ArtifactProgress(
            artifact.id, user, state, NOW + timedelta(minutes=minutes)
        )

    async with uow_factory() as uow:
        assert await uow.progress.get(artifact.id, me) is None
        await uow.progress.upsert(progress(me, {"known": ["c1"]}, 1))
        await uow.progress.upsert(progress(other, {"known": []}, 1))
        await uow.commit()
    async with uow_factory() as uow:
        await uow.progress.upsert(progress(me, {"known": ["c1", "c2"], "pos": 2}, 5))
        await uow.commit()
    async with uow_factory() as uow:
        mine = await uow.progress.get(artifact.id, me)
        theirs = await uow.progress.get(artifact.id, other)

    assert mine == progress(me, {"known": ["c1", "c2"], "pos": 2}, 5)
    assert theirs == progress(other, {"known": []}, 1)
