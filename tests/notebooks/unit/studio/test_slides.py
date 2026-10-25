"""NB-8: editing a slide deck and regenerating only the slides that were named."""

import copy
import json
from typing import Any

from app.modules.notebooks.domain.entities import Artifact, Notebook, Source
from app.modules.notebooks.domain.enums import ArtifactKind, ArtifactStatus
from app.modules.notebooks.domain.errors import (
    ArtifactNotReadyError,
    InvalidOptionsError,
    QuotaExceededError,
)
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.modules.notebooks.wiring_core import NotebooksCore
from app.modules.notebooks.wiring_studio import StudioServices
from app.shared.actor import Actor
from app.shared.contracts.ai import AiProviderError
from tests.factories.notebooks import make_artifact
from tests.fakes.tasks import FakeTaskKicker
from tests.notebooks.unit.studio.helpers import Build, HookedLlm, generate, stored

import pytest

CHANGES = [
    {"slide_id": "s2", "instruction": "Make it shorter"},
    {"slide_id": "s4", "instruction": "Add an example"},
]
NAMED = {"s2", "s4"}


@pytest.fixture
async def deck(
    studio: StudioServices,
    uow_factory: UowFactory,
    student: Actor,
    notebook: Notebook,
    source: Source,
) -> Artifact:
    """A generated slide deck (title, agenda, content slides and a summary)."""
    deck = await generate(studio, uow_factory, student, notebook, ArtifactKind.SLIDES)
    assert deck.status is ArtifactStatus.READY
    assert deck.content is not None
    return deck


def content_of(artifact: Artifact) -> dict[str, Any]:
    """The stored document of an output."""
    assert artifact.content is not None
    return artifact.content


def slides_of(artifact: Artifact) -> list[dict[str, Any]]:
    """The slides of a deck."""
    slides: list[dict[str, Any]] = content_of(artifact)["slides"]
    return slides


def canonical(value: Any) -> str:
    """A form of a document that compares byte for byte."""
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


# - - - Edit - - -


async def test_edit_changes_titles_order_and_deletes_slides(
    studio: StudioServices,
    student: Actor,
    notebook: Notebook,
    deck: Artifact,
    uow_factory: UowFactory,
) -> None:
    """NB-8: titles, order and deleted slides are saved; ids and the rest stay."""
    slides = copy.deepcopy(slides_of(deck))
    slides[1]["title"] = "Two stages of photosynthesis"
    del slides[4]
    slides[2], slides[3] = slides[3], slides[2]
    expected = ["s1", "s2", "s4", "s3", *[f"s{n}" for n in range(6, len(slides) + 2)]]

    view = await studio.edit_slides.execute(student, notebook.id, deck.id, slides)

    new = slides_of(view.artifact)
    assert [s["id"] for s in new] == expected
    assert new[1]["title"] == "Two stages of photosynthesis"
    assert content_of(view.artifact)["title"] == content_of(deck)["title"]
    assert view.progress_state is None
    saved = await stored(uow_factory, deck.id)
    assert saved.content == view.artifact.content
    assert saved.refs_index == deck.refs_index


async def test_edit_keeps_only_refs_that_exist_in_the_deck(
    studio: StudioServices,
    student: Actor,
    notebook: Notebook,
    deck: Artifact,
) -> None:
    """NB-20: an edited slide cannot cite a passage the deck does not know."""
    slides = copy.deepcopy(slides_of(deck))
    slides[1]["refs"] = ["S9:P9", "S1:P1"]

    view = await studio.edit_slides.execute(student, notebook.id, deck.id, slides)

    assert slides_of(view.artifact)[1]["refs"] == ["S1:P1"]


@pytest.mark.parametrize("problem", ["no-slides", "repeated-id"])
async def test_edit_with_unusable_slides_is_refused_and_changes_nothing(
    studio: StudioServices,
    student: Actor,
    notebook: Notebook,
    deck: Artifact,
    uow_factory: UowFactory,
    problem: str,
) -> None:
    """NB-20: edits are validated like generated slides."""
    slides = copy.deepcopy(slides_of(deck))
    edited = [] if problem == "no-slides" else [slides[0], slides[0]]

    with pytest.raises(InvalidOptionsError):
        await studio.edit_slides.execute(student, notebook.id, deck.id, edited)

    assert (await stored(uow_factory, deck.id)).content == deck.content


async def test_only_a_ready_deck_can_be_edited(
    studio: StudioServices,
    student: Actor,
    notebook: Notebook,
    uow_factory: UowFactory,
) -> None:
    """NB-8: other kinds are refused; a deck that is not ready answers 409."""
    quiz = await make_artifact(uow_factory, notebook, ArtifactKind.QUIZ)
    queued = await make_artifact(
        uow_factory, notebook, ArtifactKind.SLIDES, ArtifactStatus.QUEUED
    )

    with pytest.raises(InvalidOptionsError):
        await studio.edit_slides.execute(student, notebook.id, quiz.id, [])
    with pytest.raises(ArtifactNotReadyError):
        await studio.edit_slides.execute(student, notebook.id, queued.id, [])


# - - - Revise - - -


async def test_revise_queues_a_new_deck_that_remembers_its_parent(
    studio: StudioServices,
    core: NotebooksCore,
    student: Actor,
    notebook: Notebook,
    deck: Artifact,
    kicker: FakeTaskKicker,
) -> None:
    """NB-8: a revision is a new queued output, one more slides request."""
    revision = await studio.revise_slides.execute(
        student, notebook.id, deck.id, CHANGES
    )

    assert revision.id != deck.id
    assert revision.status is ArtifactStatus.QUEUED
    assert (revision.kind, revision.parent_id) == (ArtifactKind.SLIDES, deck.id)
    assert revision.title == deck.title
    assert revision.options["revise"] == {"changes": CHANGES}
    assert revision.options["format"] == deck.options["format"]
    assert revision.source_ids == deck.source_ids
    assert revision.source_map == deck.source_map
    assert kicker.calls[-1] == (
        "notebooks.generate_artifact",
        {"artifact_id": str(revision.id)},
    )
    assert (await core.quota.snapshot(student.user_id))["slides"].used == 2


async def test_revise_regenerates_only_the_named_slides(
    studio: StudioServices,
    student: Actor,
    notebook: Notebook,
    deck: Artifact,
    uow_factory: UowFactory,
    scripted_llm: HookedLlm,
) -> None:
    """NB-8: named slides are rewritten; the others stay byte for byte; no sources."""
    revision = await studio.revise_slides.execute(
        student, notebook.id, deck.id, CHANGES
    )

    await studio.generate_artifact.execute(revision.id)

    done = await stored(uow_factory, revision.id)
    old, new = slides_of(deck), slides_of(done)
    assert done.status is ArtifactStatus.READY
    assert [s["id"] for s in new] == [s["id"] for s in old]
    for before, after in zip(old, new, strict=True):
        if before["id"] in NAMED:
            assert after["title"] == f"{before['title']} (revised)"
        else:
            assert canonical(after) == canonical(before)
    assert done.refs_index == deck.refs_index
    assert done.source_map == deck.source_map
    assert done.sampled == deck.sampled
    assert done.title == deck.title
    assert (await stored(uow_factory, deck.id)).content == deck.content
    request = scripted_llm.json_requests[-1]
    assert request["schema_name"] == "nb_slides_revise"
    assert request["max_tokens"] == 6000
    assert "<sources>" not in json.dumps(request["messages"])
    assert len(request["messages"]) == 1
    assert "revises an existing slide deck" in request["system"]


async def test_revise_gets_a_repair_call_when_no_named_slide_comes_back(
    studio: StudioServices,
    student: Actor,
    notebook: Notebook,
    deck: Artifact,
    uow_factory: UowFactory,
    scripted_llm: HookedLlm,
) -> None:
    """NB-20: an answer without the named slides is repaired once."""
    second = {**copy.deepcopy(slides_of(deck)[1]), "title": "Revised second slide"}
    scripted_llm.queue_json({"slides": []})
    scripted_llm.queue_json({"slides": [second]})
    revision = await studio.revise_slides.execute(
        student, notebook.id, deck.id, CHANGES
    )

    await studio.generate_artifact.execute(revision.id)

    done = await stored(uow_factory, revision.id)
    repair = scripted_llm.json_requests[-1]["messages"]
    assert done.status is ArtifactStatus.READY
    assert [m["role"] for m in repair] == ["user", "assistant", "user"]
    assert slides_of(done)[1]["title"] == "Revised second slide"
    assert canonical(slides_of(done)[3]) == canonical(slides_of(deck)[3])


async def test_revise_that_stays_empty_fails_with_invalid_output(
    studio: StudioServices,
    student: Actor,
    notebook: Notebook,
    deck: Artifact,
    uow_factory: UowFactory,
    scripted_llm: HookedLlm,
) -> None:
    """NB-20: two empty answers fail the revision; the original deck is untouched."""
    scripted_llm.queue_json({"slides": []})
    scripted_llm.queue_json({"slides": []})
    revision = await studio.revise_slides.execute(
        student, notebook.id, deck.id, CHANGES
    )

    await studio.generate_artifact.execute(revision.id)

    done = await stored(uow_factory, revision.id)
    assert done.status is ArtifactStatus.FAILED
    assert done.error is not None
    assert done.error.code == "invalid_output"
    assert (await stored(uow_factory, deck.id)).content == deck.content


async def test_failed_revision_is_retried_as_a_revision(
    studio: StudioServices,
    student: Actor,
    notebook: Notebook,
    deck: Artifact,
    uow_factory: UowFactory,
    scripted_llm: HookedLlm,
) -> None:
    """NB-9: a retry of a revision revises again; it does not generate a new deck."""
    for _ in range(3):
        scripted_llm.queue_error(AiProviderError())
    revision = await studio.revise_slides.execute(
        student, notebook.id, deck.id, CHANGES
    )
    await studio.generate_artifact.execute(revision.id)
    assert (await stored(uow_factory, revision.id)).status is ArtifactStatus.FAILED

    await studio.retry_artifact.execute(student, notebook.id, revision.id)
    await studio.generate_artifact.execute(revision.id)

    done = await stored(uow_factory, revision.id)
    assert done.status is ArtifactStatus.READY
    assert scripted_llm.json_requests[-1]["schema_name"] == "nb_slides_revise"
    assert slides_of(done)[1]["title"].endswith("(revised)")


@pytest.mark.parametrize(
    "changes",
    [
        [],
        [{"slide_id": "s99", "instruction": "Unknown slide"}],
        [{"slide_id": "s2", "instruction": "   "}],
        [{"slide_id": "s2", "instruction": "x" * 501}],
        [
            {"slide_id": "s2", "instruction": "Shorter"},
            {"slide_id": "s2", "instruction": "Longer"},
        ],
        [{"slide_id": f"s{n}", "instruction": "Change"} for n in range(1, 12)],
    ],
    ids=["none", "unknown-slide", "blank", "too-long", "same-slide-twice", "eleven"],
)
async def test_revise_with_wrong_changes_is_refused_before_anything_is_counted(
    studio: StudioServices,
    core: NotebooksCore,
    student: Actor,
    notebook: Notebook,
    deck: Artifact,
    kicker: FakeTaskKicker,
    changes: list[dict[str, Any]],
) -> None:
    """NB-20: 1 to 10 changes of existing slides, 1 to 500 characters each."""
    kicks = len(kicker.calls)

    with pytest.raises(InvalidOptionsError):
        await studio.revise_slides.execute(student, notebook.id, deck.id, changes)

    assert len(kicker.calls) == kicks
    assert (await core.quota.snapshot(student.user_id))["slides"].used == 1


async def test_revise_is_one_more_slides_request_for_the_quota(
    build: Build,
    student: Actor,
    notebook: Notebook,
    source: Source,
    uow_factory: UowFactory,
) -> None:
    """NB-14: with one slides request a day, the revision is refused (429)."""
    studio = build(limits={"nb_slides_per_day": 1})
    deck = await generate(studio, uow_factory, student, notebook, ArtifactKind.SLIDES)

    with pytest.raises(QuotaExceededError):
        await studio.revise_slides.execute(student, notebook.id, deck.id, CHANGES)


async def test_only_a_ready_deck_can_be_revised(
    studio: StudioServices,
    student: Actor,
    notebook: Notebook,
    uow_factory: UowFactory,
) -> None:
    """NB-8: other kinds are refused; a deck that is not ready answers 409."""
    quiz = await make_artifact(uow_factory, notebook, ArtifactKind.QUIZ)
    queued = await make_artifact(
        uow_factory, notebook, ArtifactKind.SLIDES, ArtifactStatus.QUEUED
    )

    with pytest.raises(InvalidOptionsError):
        await studio.revise_slides.execute(student, notebook.id, quiz.id, CHANGES)
    with pytest.raises(ArtifactNotReadyError):
        await studio.revise_slides.execute(student, notebook.id, queued.id, CHANGES)
