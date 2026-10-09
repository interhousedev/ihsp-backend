"""NB-AUTO: a Studio output made for one student is served to the next who asks."""

from uuid import UUID

from app.modules.notebooks.domain.entities import Notebook, Source
from app.modules.notebooks.domain.enums import ArtifactKind, ArtifactStatus
from app.modules.notebooks.domain.errors import ArtifactLimitError
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.modules.notebooks.wiring_core import NotebooksCore
from app.modules.notebooks.wiring_studio import StudioServices
from app.shared.actor import Actor
from app.shared.contracts.ai import AiProviderError
from tests.factories.notebooks import make_notebook, make_source
from tests.fakes.tasks import FakeTaskKicker
from tests.notebooks.unit.studio.helpers import (
    SOURCE_TEXTS,
    Build,
    HookedLlm,
    generate,
    stored,
)
from tests.notebooks.unit.studio.test_generate_artifact import used_today

import pytest


@pytest.fixture
async def their_notebook(
    uow_factory: UowFactory, other_student: Actor
) -> tuple[Notebook, Source]:
    """The other student's notebook with the same text as `source`."""
    book = await make_notebook(uow_factory, other_student.user_id, title="Bio")
    own = await make_source(uow_factory, book, title="My copy", texts=SOURCE_TEXTS)
    return book, own


async def test_the_second_student_gets_the_output_at_once_without_a_model_call(
    studio: StudioServices,
    core: NotebooksCore,
    uow_factory: UowFactory,
    scripted_llm: HookedLlm,
    kicker: FakeTaskKicker,
    student: Actor,
    other_student: Actor,
    notebook: Notebook,
    source: Source,
    their_notebook: tuple[Notebook, Source],
) -> None:
    """NB-AUTO: same texts, kind, options and language: ready, no tokens, no quota."""
    book, theirs = their_notebook
    first = await generate(
        studio, uow_factory, student, notebook, ArtifactKind.QUIZ, {}
    )
    calls = scripted_llm.calls
    kicker.calls.clear()

    second = await studio.request_artifact.execute(
        other_student, book.id, ArtifactKind.QUIZ, {}, None
    )

    assert second.status is ArtifactStatus.READY and second.from_cache
    assert second.id != first.id and second.owner_id == other_student.user_id
    assert second.content == first.content and second.title == first.title
    assert second.source_ids == [theirs.id]
    assert set(second.source_map.values()) == {str(theirs.id)}
    assert second.tokens_in is None and second.weighted is None
    assert scripted_llm.calls == calls and kicker.calls == []
    assert await used_today(core, other_student) == 0
    assert (await core.budget.usage(other_student.user_id)).session.used == 0
    saved = await stored(uow_factory, second.id)
    assert saved.cache_key == first.cache_key is not None and saved.unread


async def test_the_cited_passages_point_at_the_second_students_own_sources(
    studio: StudioServices,
    uow_factory: UowFactory,
    student: Actor,
    other_student: Actor,
    notebook: Notebook,
    source: Source,
    their_notebook: tuple[Notebook, Source],
) -> None:
    """NB-AUTO: citations resolve in the other notebook (shared passages)."""
    book, theirs = their_notebook
    first = await generate(
        studio, uow_factory, student, notebook, ArtifactKind.QUIZ, {}
    )
    second = await studio.request_artifact.execute(
        other_student, book.id, ArtifactKind.QUIZ, {}, None
    )

    assert first.refs_index and second.refs_index
    assert set(second.refs_index) == set(first.refs_index)
    for label, ref in second.refs_index.items():
        assert ref["source_id"] == str(theirs.id), label
        assert ref["passage_id"] == first.refs_index[label]["passage_id"]
        async with uow_factory() as uow:
            passage = await uow.passages.get(UUID(ref["passage_id"]), book.id)
        assert passage is not None and passage.source_id == theirs.id


async def test_a_custom_focus_is_never_shared(
    studio: StudioServices,
    uow_factory: UowFactory,
    scripted_llm: HookedLlm,
    student: Actor,
    other_student: Actor,
    notebook: Notebook,
    source: Source,
    their_notebook: tuple[Notebook, Source],
) -> None:
    """NB-AUTO: the focus text is the student's own question."""
    book, _ = their_notebook
    await generate(
        studio,
        uow_factory,
        student,
        notebook,
        ArtifactKind.QUIZ,
        {},
        prompt="Only the Calvin cycle",
    )

    second = await studio.request_artifact.execute(
        other_student, book.id, ArtifactKind.QUIZ, {}, "Only the Calvin cycle"
    )

    assert second.status is ArtifactStatus.QUEUED and not second.from_cache


@pytest.mark.parametrize(
    "other_options",
    [{"language": "ru"}, {"count": "more"}],
    ids=["another language", "other options"],
)
async def test_other_options_or_language_are_a_new_request(
    studio: StudioServices,
    uow_factory: UowFactory,
    student: Actor,
    other_student: Actor,
    notebook: Notebook,
    source: Source,
    their_notebook: tuple[Notebook, Source],
    other_options: dict[str, object],
) -> None:
    """NB-AUTO: a Russian quiz is not served to someone who asked for English."""
    book, _ = their_notebook
    await generate(studio, uow_factory, student, notebook, ArtifactKind.QUIZ, {})

    second = await studio.request_artifact.execute(
        other_student, book.id, ArtifactKind.QUIZ, other_options, None
    )

    assert second.status is ArtifactStatus.QUEUED


async def test_a_different_set_of_texts_is_a_new_request(
    studio: StudioServices,
    uow_factory: UowFactory,
    student: Actor,
    other_student: Actor,
    notebook: Notebook,
    source: Source,
    their_notebook: tuple[Notebook, Source],
) -> None:
    """NB-AUTO: an extra file in the other notebook changes what the output covers."""
    book, _ = their_notebook
    await make_source(
        uow_factory, book, title="Extra", texts=("A second file about cells. " * 20,)
    )
    await generate(studio, uow_factory, student, notebook, ArtifactKind.QUIZ, {})

    second = await studio.request_artifact.execute(
        other_student, book.id, ArtifactKind.QUIZ, {}, None
    )

    assert second.status is ArtifactStatus.QUEUED


async def test_a_failed_output_is_not_shared(
    build: Build,
    uow_factory: UowFactory,
    scripted_llm: HookedLlm,
    student: Actor,
    other_student: Actor,
    notebook: Notebook,
    source: Source,
    their_notebook: tuple[Notebook, Source],
) -> None:
    """NB-AUTO: only a finished output goes into the shared cache."""
    studio = build()
    book, _ = their_notebook
    for _ in range(3):
        scripted_llm.queue_error(AiProviderError())
    failed = await generate(
        studio, uow_factory, student, notebook, ArtifactKind.QUIZ, {}
    )
    assert failed.status is ArtifactStatus.FAILED

    second = await studio.request_artifact.execute(
        other_student, book.id, ArtifactKind.QUIZ, {}, None
    )

    assert second.status is ArtifactStatus.QUEUED


async def test_a_shared_output_still_counts_against_the_notebooks_room(
    build: Build,
    uow_factory: UowFactory,
    student: Actor,
    other_student: Actor,
    notebook: Notebook,
    source: Source,
    their_notebook: tuple[Notebook, Source],
) -> None:
    """NB-AUTO: the limit of outputs per notebook applies to cached copies too."""
    studio = build(notebooks={"max_artifacts": 1})
    book, _ = their_notebook
    await generate(studio, uow_factory, student, notebook, ArtifactKind.QUIZ, {})
    await studio.request_artifact.execute(
        other_student, book.id, ArtifactKind.QUIZ, {}, None
    )

    with pytest.raises(ArtifactLimitError):
        await studio.request_artifact.execute(
            other_student, book.id, ArtifactKind.QUIZ, {}, None
        )
