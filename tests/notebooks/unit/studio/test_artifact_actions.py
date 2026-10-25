"""NB-10, NB-13: progress, "Add as source" and "Save as flash card set"."""

from typing import Any
from uuid import UUID

from app.modules.notebooks.domain.entities import Notebook, Source
from app.modules.notebooks.domain.enums import (
    ArtifactKind,
    ArtifactStatus,
    SourceKind,
    SourceStatus,
)
from app.modules.notebooks.domain.errors import (
    ArtifactNotReadyError,
    InvalidOptionsError,
)
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.modules.notebooks.wiring_studio import StudioServices
from app.shared.actor import Actor
from tests.factories.notebooks import make_artifact
from tests.fakes.ai.contracts import FakeFlashcards
from tests.fakes.clock import FixedClock
from tests.fakes.tasks import FakeTaskKicker
from tests.notebooks.unit.studio.helpers import generate, stored

import pytest

# - - - Progress - - -


@pytest.mark.parametrize("kind", [ArtifactKind.FLASHCARDS, ArtifactKind.QUIZ])
async def test_progress_is_saved_replaced_and_read_back(
    studio: StudioServices,
    student: Actor,
    notebook: Notebook,
    uow_factory: UowFactory,
    kind: ArtifactKind,
) -> None:
    """NB-10, NB-11: the student resumes where they stopped."""
    artifact = await make_artifact(uow_factory, notebook, kind)

    await studio.save_progress.execute(
        student, notebook.id, artifact.id, {"known": ["c1"], "position": 1}
    )
    await studio.save_progress.execute(
        student, notebook.id, artifact.id, {"known": ["c1", "c2"], "position": 2}
    )

    opened = await studio.get_artifact.execute(student, notebook.id, artifact.id)
    assert opened.progress_state == {"known": ["c1", "c2"], "position": 2}


async def test_progress_is_stored_per_student_and_output(
    studio: StudioServices,
    student: Actor,
    notebook: Notebook,
    uow_factory: UowFactory,
    clock: FixedClock,
) -> None:
    """NB-10: one progress row per student and output, stamped with the time."""
    artifact = await make_artifact(uow_factory, notebook, ArtifactKind.QUIZ)

    await studio.save_progress.execute(student, notebook.id, artifact.id, {"a": 1})

    async with uow_factory() as uow:
        mine = await uow.progress.get(artifact.id, student.user_id)
        theirs = await uow.progress.get(artifact.id, UUID(int=7))
    assert mine is not None
    assert (mine.state, mine.updated_at) == ({"a": 1}, clock.now())
    assert theirs is None


async def test_progress_over_16_kb_is_refused_and_under_is_accepted(
    studio: StudioServices,
    student: Actor,
    notebook: Notebook,
    uow_factory: UowFactory,
) -> None:
    """NB-10: the saved state is at most 16 KB."""
    artifact = await make_artifact(uow_factory, notebook, ArtifactKind.QUIZ)
    await studio.save_progress.execute(
        student, notebook.id, artifact.id, {"answers": "a" * 16_000}
    )

    with pytest.raises(InvalidOptionsError):
        await studio.save_progress.execute(
            student, notebook.id, artifact.id, {"answers": "a" * 17_000}
        )

    opened = await studio.get_artifact.execute(student, notebook.id, artifact.id)
    assert opened.progress_state == {"answers": "a" * 16_000}


async def test_progress_needs_a_ready_deck_or_quiz(
    studio: StudioServices,
    student: Actor,
    notebook: Notebook,
    uow_factory: UowFactory,
) -> None:
    """NB-10: other kinds have no progress; an unfinished output has nothing to save."""
    report = await make_artifact(uow_factory, notebook, ArtifactKind.REPORT)
    unfinished = await make_artifact(
        uow_factory, notebook, ArtifactKind.QUIZ, ArtifactStatus.GENERATING
    )

    with pytest.raises(InvalidOptionsError):
        await studio.save_progress.execute(student, notebook.id, report.id, {})
    with pytest.raises(ArtifactNotReadyError):
        await studio.save_progress.execute(student, notebook.id, unfinished.id, {})


# - - - Add as source - - -


async def test_report_becomes_a_note_source_without_citation_markers(
    studio: StudioServices,
    student: Actor,
    notebook: Notebook,
    source: Source,
    uow_factory: UowFactory,
    kicker: FakeTaskKicker,
) -> None:
    """NB-13: the note has the report's text, no `⟦n⟧` markers and no citations."""
    report = await generate(
        studio,
        uow_factory,
        student,
        notebook,
        ArtifactKind.REPORT,
        {"format": "conspect"},
    )
    assert report.content is not None
    assert "⟦" in report.content["markdown"]

    note = await studio.save_as_source.execute(student, notebook.id, report.id)

    assert note.kind is SourceKind.NOTE
    assert note.title == report.title
    assert note.status is SourceStatus.PENDING
    assert note.selected
    assert note.citations is None
    assert note.body_md is not None
    assert "⟦" not in note.body_md
    assert "## Main idea" in note.body_md
    assert (
        "notebooks.process_source",
        {"source_id": str(note.id)},
    ) in kicker.calls
    async with uow_factory() as uow:
        saved = await uow.notebooks.get(notebook.id)
        listed = await uow.sources.list_for_notebook(notebook.id)
    assert saved is not None
    assert saved.source_count == 2
    assert [s.id for s in listed] == [source.id, note.id]


async def test_only_a_ready_report_can_be_added_as_a_source(
    studio: StudioServices,
    student: Actor,
    notebook: Notebook,
    uow_factory: UowFactory,
) -> None:
    """NB-13: other kinds are refused; a report that is not ready answers 409."""
    quiz = await make_artifact(uow_factory, notebook, ArtifactKind.QUIZ)
    queued = await make_artifact(
        uow_factory, notebook, ArtifactKind.REPORT, ArtifactStatus.QUEUED
    )

    with pytest.raises(InvalidOptionsError):
        await studio.save_as_source.execute(student, notebook.id, quiz.id)
    with pytest.raises(ArtifactNotReadyError):
        await studio.save_as_source.execute(student, notebook.id, queued.id)


# - - - Flash card set - - -


async def test_flashcards_become_one_flash_card_set_and_asking_again_returns_it(
    studio: StudioServices,
    student: Actor,
    notebook: Notebook,
    source: Source,
    uow_factory: UowFactory,
    flashcards: FakeFlashcards,
) -> None:
    """NB-10: the bridge creates ONE set (source `ai`) and is idempotent."""
    deck = await generate(
        studio, uow_factory, student, notebook, ArtifactKind.FLASHCARDS, {}
    )
    assert deck.content is not None
    cards = deck.content["cards"]

    first_id, first_created = await studio.save_flashcard_set.execute(
        student, notebook.id, deck.id
    )
    second_id, second_created = await studio.save_flashcard_set.execute(
        student, notebook.id, deck.id
    )

    assert (first_created, second_created) == (True, False)
    assert first_id == second_id
    assert len(flashcards.create_calls) == 1
    call = flashcards.create_calls[0]
    assert call["source"] == "ai"
    assert call["title"] == deck.title
    assert call["cards"] == [(card["front"], card["back"]) for card in cards]
    assert flashcards.sets[first_id]["owner_id"] == student.user_id
    assert (await stored(uow_factory, deck.id)).flashcard_set_id == first_id


async def test_cards_are_trimmed_to_the_flash_card_limits(
    studio: StudioServices,
    student: Actor,
    notebook: Notebook,
    uow_factory: UowFactory,
    flashcards: FakeFlashcards,
) -> None:
    """NB-10: texts are cut at 2 000 characters, empty cards dropped, 500 at most."""
    raw: list[dict[str, Any]] = [
        {"front": "q" * 2500, "back": " a "},
        {"front": "", "back": "no front"},
        {"front": "no back", "back": " "},
    ] + [{"front": f"Q{n}", "back": f"A{n}"} for n in range(600)]
    deck = await make_artifact(
        uow_factory,
        notebook,
        ArtifactKind.FLASHCARDS,
        content={"title": "Big deck", "cards": raw},
    )

    await studio.save_flashcard_set.execute(student, notebook.id, deck.id)

    cards = flashcards.create_calls[0]["cards"]
    assert len(cards) == 500
    assert cards[0] == ("q" * 2000, "a")
    assert cards[1] == ("Q0", "A0")


async def test_deck_without_usable_cards_is_refused(
    studio: StudioServices,
    student: Actor,
    notebook: Notebook,
    uow_factory: UowFactory,
    flashcards: FakeFlashcards,
) -> None:
    """NB-10: nothing to save means a validation error and no set."""
    deck = await make_artifact(
        uow_factory,
        notebook,
        ArtifactKind.FLASHCARDS,
        content={"title": "Empty", "cards": [{"front": "", "back": ""}]},
    )

    with pytest.raises(InvalidOptionsError):
        await studio.save_flashcard_set.execute(student, notebook.id, deck.id)

    assert flashcards.create_calls == []


async def test_only_a_ready_deck_can_be_saved_as_a_set(
    studio: StudioServices,
    student: Actor,
    notebook: Notebook,
    uow_factory: UowFactory,
) -> None:
    """NB-10: other kinds are refused; a deck that is not ready answers 409."""
    quiz = await make_artifact(uow_factory, notebook, ArtifactKind.QUIZ)
    failed = await make_artifact(
        uow_factory, notebook, ArtifactKind.FLASHCARDS, ArtifactStatus.FAILED
    )

    with pytest.raises(InvalidOptionsError):
        await studio.save_flashcard_set.execute(student, notebook.id, quiz.id)
    with pytest.raises(ArtifactNotReadyError):
        await studio.save_flashcard_set.execute(student, notebook.id, failed.id)
