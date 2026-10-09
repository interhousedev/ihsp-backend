"""LMS-AI-STUDIO: previewing and applying outputs to the course draft."""

import copy
from typing import Any, cast

from app.modules.lms.domain.authoring.errors import DraftConflictError
from app.modules.notebooks.application.apply_course_artifact import ApplyCourseArtifact
from app.modules.notebooks.application.apply_views import ApplyRequest
from app.modules.notebooks.application.public_commands import NotebooksCommandsImpl
from app.modules.notebooks.domain.entities import Notebook
from app.modules.notebooks.domain.enums import ArtifactKind, ArtifactStatus
from app.modules.notebooks.domain.errors import (
    ArtifactNotReadyError,
    FeatureDisabledError,
    InvalidOptionsError,
    NotebookNotFoundError,
    OutputInvalidError,
    WorkspaceReadOnlyError,
)
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.modules.notebooks.wiring_studio import StudioServices
from app.shared.actor import Actor
from app.shared.contracts.lms_blocks import (
    CoursePlanInput,
    PlanSectionInput,
    PlanStepInput,
    StepDraftInput,
    TextBlockInput,
)
from tests.factories.notebooks import make_artifact, make_notebook
from tests.fakes.notebooks.lms_apply import FakeCourseDraft, FakeStep
from tests.notebooks.course_studio.support import DECK, LESSON, PLAN, QUIZ, ready

import pytest


def step_of(draft: FakeCourseDraft, title: str) -> FakeStep:
    return next(s for s in draft.steps.values() if s.title == title)


def types(step: FakeStep) -> list[str]:
    return [block["type"] for block in step.blocks]


# - - - Course plan - - -


async def test_plan_preview_marks_new_and_existing_and_writes_nothing(
    studio: StudioServices,
    uow_factory: UowFactory,
    editor: Actor,
    workspace: Notebook,
    draft: FakeCourseDraft,
) -> None:
    """LMS-AI-STUDIO: the dry run says what would be created; the draft is untouched."""
    artifact = await ready(uow_factory, workspace, ArtifactKind.COURSE_PLAN, PLAN)

    view = await studio.apply_course_artifact.preview(
        editor, workspace.id, artifact.id, ApplyRequest()
    )

    assert view.can_apply and view.problems == [] and view.step is None
    assert view.plan is not None
    assert (view.plan.new_sections, view.plan.new_steps, view.plan.existing_steps) == (
        1,
        2,
        1,
    )
    light, calvin = view.plan.sections
    assert (light.action, calvin.action) == ("exists", "new")
    assert [(s.title, s.action) for s in light.steps] == [
        ("Photons", "exists"),
        ("Pigments", "new"),
    ]
    assert draft.calls == ["apply_outline_dry"]
    assert len(draft.sections) == 1 and len(draft.steps) == 1


async def test_plan_apply_creates_what_is_missing_and_is_repeatable(
    studio: StudioServices,
    uow_factory: UowFactory,
    editor: Actor,
    workspace: Notebook,
    draft: FakeCourseDraft,
) -> None:
    """LMS-AI-STUDIO: the second apply finds everything and creates nothing."""
    artifact = await ready(uow_factory, workspace, ArtifactKind.COURSE_PLAN, PLAN)

    first = await studio.apply_course_artifact.apply(
        editor, workspace.id, artifact.id, ApplyRequest()
    )
    second = await studio.apply_course_artifact.apply(
        editor, workspace.id, artifact.id, ApplyRequest()
    )

    assert [s["title"] for s in first.created_sections] == ["Calvin cycle"]
    assert [s["title"] for s in first.created_steps] == ["Pigments", "Carbon fixation"]
    assert first.step_id is None and first.draft_seq == draft.draft_seq
    assert second.created_sections == [] and second.created_steps == []
    assert [s.title for s in draft.sections] == ["Light reactions", "Calvin cycle"]
    assert len(draft.steps) == 3


async def test_plan_briefs_are_written_only_when_asked_and_in_the_plans_language(
    studio: StudioServices,
    uow_factory: UowFactory,
    editor: Actor,
    workspace: Notebook,
    draft: FakeCourseDraft,
) -> None:
    """LMS-AI-STUDIO: add_briefs puts goals and summary into a new step's text."""
    plan = {**copy.deepcopy(PLAN), "language": "ru"}
    artifact = await ready(uow_factory, workspace, ArtifactKind.COURSE_PLAN, plan)

    await studio.apply_course_artifact.apply(
        editor, workspace.id, artifact.id, ApplyRequest(add_briefs=True)
    )

    pigments = step_of(draft, "Pigments")
    assert pigments.blocks[0]["markdown"].startswith("**Цели обучения**")
    assert "Name the pigments" in pigments.blocks[0]["markdown"]
    assert step_of(draft, "Photons").blocks == []  # existing steps are never touched


async def test_an_edited_plan_in_the_body_wins_over_the_stored_one(
    studio: StudioServices,
    uow_factory: UowFactory,
    editor: Actor,
    workspace: Notebook,
    draft: FakeCourseDraft,
) -> None:
    """LMS-AI-STUDIO: the author edits the plan tree in the viewer."""
    artifact = await ready(uow_factory, workspace, ArtifactKind.COURSE_PLAN, PLAN)
    edited = CoursePlanInput(
        sections=[
            PlanSectionInput(
                title="Light reactions",
                steps=[PlanStepInput(title="My own step [S1:P1]")],
            )
        ]
    )

    result = await studio.apply_course_artifact.apply(
        editor, workspace.id, artifact.id, ApplyRequest(plan=edited)
    )

    assert [s["title"] for s in result.created_steps] == ["My own step"]
    assert {s.title for s in draft.steps.values()} == {"Photons", "My own step"}


async def test_an_edited_plan_with_an_empty_title_cannot_be_applied(
    studio: StudioServices,
    uow_factory: UowFactory,
    editor: Actor,
    workspace: Notebook,
    draft: FakeCourseDraft,
) -> None:
    """LMS-AI-STUDIO: the preview lists the problem, apply answers output-invalid."""
    artifact = await ready(uow_factory, workspace, ArtifactKind.COURSE_PLAN, PLAN)
    label_only = CoursePlanInput(
        sections=[
            PlanSectionInput(title="S1:P1", steps=[PlanStepInput(title="Step")]),
        ]
    )

    view = await studio.apply_course_artifact.preview(
        editor, workspace.id, artifact.id, ApplyRequest(plan=label_only)
    )
    with pytest.raises(OutputInvalidError):
        await studio.apply_course_artifact.apply(
            editor, workspace.id, artifact.id, ApplyRequest(plan=label_only)
        )

    assert not view.can_apply and view.problems
    assert draft.calls == []


# - - - Lesson draft - - -


async def test_lesson_preview_shows_current_and_new_blocks_with_the_lock_version(
    studio: StudioServices,
    uow_factory: UowFactory,
    editor: Actor,
    workspace: Notebook,
    draft: FakeCourseDraft,
) -> None:
    """LMS-AI-STUDIO: the diff of a replace, the lock to send back, the notes."""
    photons = step_of(draft, "Photons")
    draft.steps[photons.id].blocks = draft._with_ids(
        [
            {"type": "text", "markdown": "Old text."},
            {"type": "test", "config": {}, "questions": []},
        ]
    )
    artifact = await ready(uow_factory, workspace, ArtifactKind.LESSON_DRAFT, LESSON)

    view = await studio.apply_course_artifact.preview(
        editor, workspace.id, artifact.id, ApplyRequest(target_step_id=photons.id)
    )

    assert view.can_apply and view.step is not None
    step = view.step
    assert (step.step_id, step.mode, step.lock_version) == (photons.id, "replace", 1)
    assert [b["type"] for b in step.current_blocks or []] == ["text", "test"]
    assert [b["type"] for b in step.new_blocks] == ["text", "flashcards"]
    assert step.title == "Light reactions"
    assert any("test block that the new version does not have" in n for n in view.notes)
    assert any("test question 3 was dropped" in n for n in view.notes)
    assert photons.lock_version == 1 and draft.calls == ["step_draft"]


async def test_lesson_replace_writes_the_blocks_and_returns_the_new_lock(
    studio: StudioServices,
    uow_factory: UowFactory,
    editor: Actor,
    workspace: Notebook,
    draft: FakeCourseDraft,
) -> None:
    """LMS-AI-STUDIO: replace is the default for a lesson; the title is the lesson's."""
    photons = step_of(draft, "Photons")
    artifact = await ready(uow_factory, workspace, ArtifactKind.LESSON_DRAFT, LESSON)

    result = await studio.apply_course_artifact.apply(
        editor,
        workspace.id,
        artifact.id,
        ApplyRequest(target_step_id=photons.id, lock_version=1),
    )

    assert result.step_id == photons.id and result.lock_version == 2
    assert result.created_steps == [] and result.draft_seq == draft.draft_seq
    assert photons.title == "Light reactions"
    assert types(photons) == ["text", "flashcards"]
    assert all(block["id"] for block in photons.blocks)  # ids by the LMS
    assert "S1:P" not in photons.blocks[0]["markdown"]


async def test_lesson_append_keeps_the_current_blocks_and_the_title(
    studio: StudioServices,
    uow_factory: UowFactory,
    editor: Actor,
    workspace: Notebook,
    draft: FakeCourseDraft,
) -> None:
    """LMS-AI-STUDIO: append adds the lesson's blocks after the existing ones."""
    photons = step_of(draft, "Photons")
    photons.blocks = draft._with_ids([{"type": "text", "markdown": "Old text."}])
    old_id = photons.blocks[0]["id"]
    artifact = await ready(uow_factory, workspace, ArtifactKind.LESSON_DRAFT, LESSON)

    await studio.apply_course_artifact.apply(
        editor,
        workspace.id,
        artifact.id,
        ApplyRequest(target_step_id=photons.id, mode="append"),
    )

    assert photons.title == "Photons"
    assert types(photons) == ["text", "text", "flashcards"]
    assert photons.blocks[0]["id"] == old_id and photons.blocks[0]["markdown"] == (
        "Old text."
    )


async def test_a_stale_lock_version_is_a_conflict_and_changes_nothing(
    studio: StudioServices,
    uow_factory: UowFactory,
    editor: Actor,
    workspace: Notebook,
    draft: FakeCourseDraft,
) -> None:
    """LMS-AI-STUDIO: the draft changed after the preview; the author is told."""
    photons = step_of(draft, "Photons")
    photons.lock_version = 5  # somebody saved meanwhile
    artifact = await ready(uow_factory, workspace, ArtifactKind.LESSON_DRAFT, LESSON)

    with pytest.raises(DraftConflictError):
        await studio.apply_course_artifact.apply(
            editor,
            workspace.id,
            artifact.id,
            ApplyRequest(target_step_id=photons.id, lock_version=1),
        )

    assert photons.title == "Photons" and photons.blocks == []


async def test_a_lesson_made_for_a_step_goes_there_by_default(
    studio: StudioServices,
    uow_factory: UowFactory,
    editor: Actor,
    workspace: Notebook,
    draft: FakeCourseDraft,
) -> None:
    """LMS-AI-STUDIO: options.step_id is the default target."""
    photons = step_of(draft, "Photons")
    artifact = await ready(
        uow_factory,
        workspace,
        ArtifactKind.LESSON_DRAFT,
        LESSON,
        options={"step_id": str(photons.id)},
    )

    result = await studio.apply_course_artifact.apply(
        editor, workspace.id, artifact.id, ApplyRequest()
    )

    assert result.step_id == photons.id
    assert photons.title == "Light reactions"


async def test_a_lesson_without_a_step_becomes_a_new_step_of_the_section(
    studio: StudioServices,
    uow_factory: UowFactory,
    editor: Actor,
    workspace: Notebook,
    draft: FakeCourseDraft,
) -> None:
    """LMS-AI-STUDIO: create_step, then replace_step with the returned lock."""
    artifact = await ready(uow_factory, workspace, ArtifactKind.LESSON_DRAFT, LESSON)
    request = ApplyRequest(target_section_id="sec-1")

    view = await studio.apply_course_artifact.preview(
        editor, workspace.id, artifact.id, request
    )
    result = await studio.apply_course_artifact.apply(
        editor, workspace.id, artifact.id, request
    )

    assert view.step is not None
    assert view.step.step_id is None and view.step.lock_version is None
    assert view.step.current_blocks is None and view.step.title == "Light reactions"
    created = step_of(draft, "Light reactions")
    assert result.step_id == created.id
    assert [(s["section_id"], s["title"]) for s in result.created_steps] == [
        ("sec-1", "Light reactions")
    ]
    assert types(created) == ["text", "flashcards"]
    assert draft.calls[-3:] == ["create_step", "replace_step", "course_detail"]


async def test_an_edited_lesson_in_the_body_wins_and_is_cleaned(
    studio: StudioServices,
    uow_factory: UowFactory,
    editor: Actor,
    workspace: Notebook,
    draft: FakeCourseDraft,
) -> None:
    """LMS-AI-STUDIO: the author edited the blocks; labels are cleaned again."""
    artifact = await ready(uow_factory, workspace, ArtifactKind.LESSON_DRAFT, LESSON)
    edited = StepDraftInput(
        title="Edited",
        blocks=[TextBlockInput(markdown="# Mine [[S1:P3]]\n\nBy hand.")],
    )

    await studio.apply_course_artifact.apply(
        editor,
        workspace.id,
        artifact.id,
        ApplyRequest(target_section_id="sec-1", draft=edited),
    )

    created = step_of(draft, "Edited")
    assert created.blocks[0]["markdown"] == "### Mine\n\nBy hand."


async def test_without_a_target_the_preview_lists_a_problem_and_apply_refuses(
    studio: StudioServices,
    uow_factory: UowFactory,
    editor: Actor,
    workspace: Notebook,
    draft: FakeCourseDraft,
) -> None:
    """LMS-AI-STUDIO: a lesson needs a step or a section."""
    artifact = await ready(uow_factory, workspace, ArtifactKind.LESSON_DRAFT, LESSON)

    view = await studio.apply_course_artifact.preview(
        editor, workspace.id, artifact.id, ApplyRequest()
    )
    with pytest.raises(InvalidOptionsError):
        await studio.apply_course_artifact.apply(
            editor, workspace.id, artifact.id, ApplyRequest()
        )

    assert not view.can_apply
    assert view.problems == ["target: choose a step, or a section for a new step"]
    assert view.step is None


async def test_a_step_of_another_course_is_refused(
    studio: StudioServices,
    uow_factory: UowFactory,
    editor: Actor,
    workspace: Notebook,
    draft: FakeCourseDraft,
) -> None:
    """LMS-AI-STUDIO: a workspace writes only into its own course."""
    photons = step_of(draft, "Photons")
    draft.foreign.add(photons.id)
    artifact = await ready(uow_factory, workspace, ArtifactKind.LESSON_DRAFT, LESSON)
    request = ApplyRequest(target_step_id=photons.id)

    view = await studio.apply_course_artifact.preview(
        editor, workspace.id, artifact.id, request
    )
    with pytest.raises(InvalidOptionsError):
        await studio.apply_course_artifact.apply(
            editor, workspace.id, artifact.id, request
        )

    assert view.problems == ["target_step_id: the step is not in this course"]
    assert photons.blocks == []


async def test_a_bad_mode_is_refused(
    studio: StudioServices,
    uow_factory: UowFactory,
    editor: Actor,
    workspace: Notebook,
    draft: FakeCourseDraft,
) -> None:
    """LMS-AI-STUDIO: the assistant may send any string as mode."""
    artifact = await ready(uow_factory, workspace, ArtifactKind.LESSON_DRAFT, LESSON)

    view = await studio.apply_course_artifact.preview(
        editor,
        workspace.id,
        artifact.id,
        ApplyRequest(target_section_id="sec-1", mode="merge"),
    )

    assert not view.can_apply and "mode" in view.problems[0]


async def test_a_failed_second_call_leaves_the_empty_new_step_and_raises(
    studio: StudioServices,
    uow_factory: UowFactory,
    editor: Actor,
    workspace: Notebook,
    draft: FakeCourseDraft,
) -> None:
    """LMS-AI-STUDIO: the two calls of a new step are not atomic; the error shows."""
    draft.fail_replace_once = OutputInvalidError(["lms said no"])
    artifact = await ready(uow_factory, workspace, ArtifactKind.LESSON_DRAFT, LESSON)

    with pytest.raises(OutputInvalidError):
        await studio.apply_course_artifact.apply(
            editor, workspace.id, artifact.id, ApplyRequest(target_section_id="sec-1")
        )

    assert step_of(draft, "Light reactions").blocks == []


# - - - Quiz and flash cards - - -


async def test_a_quiz_is_appended_to_a_step_as_a_test_block(
    studio: StudioServices,
    uow_factory: UowFactory,
    editor: Actor,
    workspace: Notebook,
    draft: FakeCourseDraft,
) -> None:
    """LMS-AI-STUDIO: append is the default for a quiz; the title stays."""
    photons = step_of(draft, "Photons")
    photons.blocks = draft._with_ids([{"type": "text", "markdown": "Intro."}])
    artifact = await ready(uow_factory, workspace, ArtifactKind.QUIZ, QUIZ)

    view = await studio.apply_course_artifact.preview(
        editor, workspace.id, artifact.id, ApplyRequest(target_step_id=photons.id)
    )
    await studio.apply_course_artifact.apply(
        editor, workspace.id, artifact.id, ApplyRequest(target_step_id=photons.id)
    )

    assert view.step is not None and view.step.mode == "append"
    assert [b["type"] for b in view.step.new_blocks] == ["test"]
    assert view.notes == [
        "1 true/false question(s) became single choice questions with two options."
    ]
    assert photons.title == "Photons"
    assert types(photons) == ["text", "test"]
    questions = photons.blocks[1]["questions"]
    assert [q["prompt"] for q in questions] == [
        "Which gas is released?",
        "Chlorophyll is green.",
    ]
    assert questions[0]["options"][0] == {
        "id": questions[0]["options"][0]["id"],
        "text": "Oxygen",
        "correct": True,
        "pinned": False,
    }


async def test_flash_cards_can_replace_a_step_or_make_a_new_one(
    studio: StudioServices,
    uow_factory: UowFactory,
    editor: Actor,
    workspace: Notebook,
    draft: FakeCourseDraft,
) -> None:
    """LMS-AI-STUDIO: replace swaps the blocks; a section makes a step."""
    photons = step_of(draft, "Photons")
    photons.blocks = draft._with_ids([{"type": "text", "markdown": "Intro."}])
    artifact = await ready(uow_factory, workspace, ArtifactKind.FLASHCARDS, DECK)

    await studio.apply_course_artifact.apply(
        editor,
        workspace.id,
        artifact.id,
        ApplyRequest(target_step_id=photons.id, mode="replace"),
    )
    made = await studio.apply_course_artifact.apply(
        editor, workspace.id, artifact.id, ApplyRequest(target_section_id="sec-1")
    )

    assert photons.title == "Photons" and types(photons) == ["flashcards"]
    assert made.created_steps[0]["title"] == "Output"
    assert types(step_of(draft, "Output")) == ["flashcards"]


# - - - Who and what may be applied - - -


async def test_only_an_editor_may_preview_or_apply(
    studio: StudioServices,
    uow_factory: UowFactory,
    reader: Actor,
    stranger: Actor,
    workspace: Notebook,
    draft: FakeCourseDraft,
) -> None:
    """LMS-AI-STUDIO: `view_drafts` is read-only, a stranger finds nothing."""
    artifact = await ready(uow_factory, workspace, ArtifactKind.COURSE_PLAN, PLAN)
    apply = studio.apply_course_artifact

    for method in (apply.preview, apply.apply):
        with pytest.raises(WorkspaceReadOnlyError):
            await method(reader, workspace.id, artifact.id, ApplyRequest())
        with pytest.raises(NotebookNotFoundError):
            await method(stranger, workspace.id, artifact.id, ApplyRequest())

    assert draft.calls == []


async def test_an_output_of_another_notebook_is_not_found(
    studio: StudioServices,
    uow_factory: UowFactory,
    editor: Actor,
    workspace: Notebook,
) -> None:
    """LMS-AI-STUDIO: the artifact must belong to the workspace in the URL."""
    other = await make_notebook(uow_factory, editor.user_id, title="Mine")
    artifact = await ready(uow_factory, other, ArtifactKind.COURSE_PLAN, PLAN)

    with pytest.raises(NotebookNotFoundError):
        await studio.apply_course_artifact.apply(
            editor, workspace.id, artifact.id, ApplyRequest()
        )


async def test_a_personal_notebook_has_nothing_to_apply_to(
    studio: StudioServices, uow_factory: UowFactory, editor: Actor
) -> None:
    """LMS-AI-STUDIO: a quiz of a private notebook cannot be applied to a course."""
    personal = await make_notebook(uow_factory, editor.user_id, title="Mine")
    artifact = await ready(uow_factory, personal, ArtifactKind.QUIZ, QUIZ)

    with pytest.raises(InvalidOptionsError):
        await studio.apply_course_artifact.apply(
            editor, personal.id, artifact.id, ApplyRequest()
        )


async def test_other_kinds_and_unfinished_outputs_are_refused(
    studio: StudioServices,
    uow_factory: UowFactory,
    editor: Actor,
    workspace: Notebook,
) -> None:
    """LMS-AI-STUDIO: only ready plans, lessons, quizzes and decks apply."""
    report = await make_artifact(uow_factory, workspace, ArtifactKind.REPORT)
    queued = await make_artifact(
        uow_factory, workspace, ArtifactKind.COURSE_PLAN, ArtifactStatus.QUEUED
    )

    with pytest.raises(InvalidOptionsError):
        await studio.apply_course_artifact.apply(
            editor, workspace.id, report.id, ApplyRequest()
        )
    with pytest.raises(ArtifactNotReadyError):
        await studio.apply_course_artifact.preview(
            editor, workspace.id, queued.id, ApplyRequest()
        )


async def test_without_the_lms_ports_the_feature_is_off(
    studio: StudioServices, uow_factory: UowFactory, editor: Actor, workspace: Notebook
) -> None:
    """LMS-AI-STUDIO: a process without the LMS answers feature-disabled."""
    artifact = await ready(uow_factory, workspace, ArtifactKind.COURSE_PLAN, PLAN)
    off = ApplyCourseArtifact(uow_factory=uow_factory)

    with pytest.raises(FeatureDisabledError):
        await off.preview(editor, workspace.id, artifact.id, ApplyRequest())


# - - - The assistant's command - - -


async def test_the_commands_contract_applies_with_the_result_dict(
    studio: StudioServices,
    uow_factory: UowFactory,
    editor: Actor,
    workspace: Notebook,
    draft: FakeCourseDraft,
) -> None:
    """LMS-AI-STUDIO: `NotebooksCommands.apply_artifact` = the HTTP apply."""
    photons = step_of(draft, "Photons")
    artifact = await ready(uow_factory, workspace, ArtifactKind.LESSON_DRAFT, LESSON)
    commands = NotebooksCommandsImpl(
        create_notebook=cast(Any, None),
        add_sources=cast(Any, None),
        request_artifact=cast(Any, None),
        apply_artifact=studio.apply_course_artifact,
    )

    result = await commands.apply_artifact(
        editor, workspace.id, artifact.id, target_step_id=photons.id, mode="replace"
    )

    assert result == {
        "kind": "lesson_draft",
        "created_sections": [],
        "created_steps": [],
        "step_id": str(photons.id),
        "lock_version": 2,
        "draft_seq": draft.draft_seq,
    }


async def test_the_commands_contract_without_the_use_case_is_disabled(
    editor: Actor, workspace: Notebook
) -> None:
    """LMS-AI-STUDIO: no LMS wired, no apply."""
    commands = NotebooksCommandsImpl(
        create_notebook=cast(Any, None),
        add_sources=cast(Any, None),
        request_artifact=cast(Any, None),
    )

    with pytest.raises(FeatureDisabledError):
        await commands.apply_artifact(editor, workspace.id, workspace.id)
