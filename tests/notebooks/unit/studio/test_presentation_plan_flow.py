"""PLAN: create, read, edit and confirm a presentation plan; the deck follows it."""

from typing import Any

from app.modules.notebooks.domain.entities import Notebook, Source
from app.modules.notebooks.domain.enums import ArtifactKind, ArtifactStatus
from app.modules.notebooks.domain.errors import (
    NotebookNotFoundError,
    PlanConfirmedError,
    PlanTooLongError,
)
from app.modules.notebooks.domain.presentation_plan import (
    PLAN_MAX_SLIDES,
    PlanSlide,
    PlanStatus,
)
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.modules.notebooks.wiring_studio import StudioServices
from app.shared.actor import Actor
from tests.fakes.tasks import FakeTaskKicker
from tests.notebooks.unit.studio.helpers import HookedLlm, stored

import pytest

OUTLINE: dict[str, Any] = {
    "title": "Photosynthesis",
    "slides": [
        {"title": "Photosynthesis", "bullets": ["What it is", "Why it matters"]},
        {"title": "Light reactions", "bullets": ["Chlorophyll", "ATP"]},
        {"title": "Calvin cycle", "bullets": ["CO2 fixation", "Sugar"]},
        {"title": "Key takeaways", "bullets": ["Light to sugar", "Oxygen"]},
    ],
}


async def test_create_asks_the_model_and_stores_a_draft(
    studio: StudioServices,
    student: Actor,
    notebook: Notebook,
    source: Source,
    scripted_llm: HookedLlm,
) -> None:
    """PLAN: the outline is made first, numbered slides with 2-5 bullets."""
    scripted_llm.queue_json(OUTLINE)

    plan = await studio.create_presentation_plan.execute(
        student, notebook.id, prompt="photosynthesis", source_ids=None
    )

    assert plan.status is PlanStatus.DRAFT
    assert plan.title == "Photosynthesis"
    assert [s.title for s in plan.slides][1] == "Light reactions"
    assert plan.source_ids == [source.id]
    request = scripted_llm.json_requests[-1]
    assert request["schema_name"] == "nb_slides_plan"
    again = await studio.get_presentation_plan.execute(student, notebook.id, plan.id)
    assert again.slides == plan.slides


async def test_a_too_long_model_outline_is_cut_to_the_limit(
    studio: StudioServices,
    student: Actor,
    notebook: Notebook,
    source: Source,
    scripted_llm: HookedLlm,
) -> None:
    """PLAN: the model's outline never exceeds the slide limit."""
    many = [{"title": f"S{n}", "bullets": ["a", "b"]} for n in range(30)]
    scripted_llm.queue_json({"title": "Big", "slides": many})

    plan = await studio.create_presentation_plan.execute(
        student, notebook.id, prompt=None, source_ids=None
    )

    assert len(plan.slides) == PLAN_MAX_SLIDES


async def test_edit_reorders_renames_and_deletes_slides(
    studio: StudioServices,
    student: Actor,
    notebook: Notebook,
    source: Source,
    scripted_llm: HookedLlm,
) -> None:
    """PLAN: the student edits titles and bullets, deletes and reorders slides."""
    scripted_llm.queue_json(OUTLINE)
    plan = await studio.create_presentation_plan.execute(
        student, notebook.id, prompt=None, source_ids=None
    )
    edited = [
        PlanSlide(title="Calvin cycle", bullets=["CO2 fixation"]),
        PlanSlide(title="  Intro ", bullets=["", "What it is"]),
        PlanSlide(title="Summary", bullets=["Light to sugar"]),
    ]

    plan = await studio.update_presentation_plan.execute(
        student, notebook.id, plan.id, title="My deck", slides=edited
    )

    assert plan.title == "My deck"
    assert [s.title for s in plan.slides] == ["Calvin cycle", "Intro", "Summary"]
    assert plan.slides[1].bullets == ["What it is"]


async def test_a_plan_over_the_limit_cannot_be_confirmed(
    studio: StudioServices,
    student: Actor,
    notebook: Notebook,
    source: Source,
    scripted_llm: HookedLlm,
) -> None:
    """PLAN: an edited plan longer than the limit is refused, with the numbers."""
    scripted_llm.queue_json(OUTLINE)
    plan = await studio.create_presentation_plan.execute(
        student, notebook.id, prompt=None, source_ids=None
    )
    long = [PlanSlide(title=f"S{n}") for n in range(PLAN_MAX_SLIDES + 2)]
    plan = await studio.update_presentation_plan.execute(
        student, notebook.id, plan.id, title=None, slides=long
    )
    assert plan.over_limit

    with pytest.raises(PlanTooLongError) as caught:
        await studio.confirm_presentation_plan.execute(student, notebook.id, plan.id)

    assert caught.value.params == {
        "count": PLAN_MAX_SLIDES + 2,
        "max": PLAN_MAX_SLIDES,
    }


async def test_confirm_queues_a_deck_that_follows_the_plan(
    studio: StudioServices,
    student: Actor,
    notebook: Notebook,
    source: Source,
    scripted_llm: HookedLlm,
    uow_factory: UowFactory,
    kicker: FakeTaskKicker,
) -> None:
    """PLAN: Generate makes the deck from the edited outline, once."""
    scripted_llm.queue_json(OUTLINE)
    plan = await studio.create_presentation_plan.execute(
        student, notebook.id, prompt=None, source_ids=None
    )

    plan, artifact = await studio.confirm_presentation_plan.execute(
        student, notebook.id, plan.id
    )

    assert plan.status is PlanStatus.CONFIRMED
    assert plan.artifact_id == artifact.id
    row = await stored(uow_factory, artifact.id)
    assert row.kind is ArtifactKind.SLIDES
    assert row.status is ArtifactStatus.QUEUED
    assert row.options["length"] == "short"
    assert [s["title"] for s in row.options["outline"]][2] == "Calvin cycle"
    with pytest.raises(PlanConfirmedError):
        await studio.confirm_presentation_plan.execute(student, notebook.id, plan.id)
    with pytest.raises(PlanConfirmedError):
        await studio.update_presentation_plan.execute(
            student, notebook.id, plan.id, title="x", slides=None
        )


async def test_another_student_cannot_see_the_plan(
    studio: StudioServices,
    student: Actor,
    other_student: Actor,
    notebook: Notebook,
    source: Source,
    scripted_llm: HookedLlm,
) -> None:
    """PLAN: a plan is private to its notebook's owner."""
    scripted_llm.queue_json(OUTLINE)
    plan = await studio.create_presentation_plan.execute(
        student, notebook.id, prompt=None, source_ids=None
    )

    with pytest.raises(NotebookNotFoundError):
        await studio.get_presentation_plan.execute(other_student, notebook.id, plan.id)
