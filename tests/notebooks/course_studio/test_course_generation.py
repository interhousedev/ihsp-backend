"""LMS-AI-STUDIO: course plans and lesson drafts through the Studio engine."""

from typing import Any

from app.modules.notebooks.domain.entities import Notebook, Source
from app.modules.notebooks.domain.enums import ArtifactKind, ArtifactStatus
from app.modules.notebooks.domain.errors import (
    InvalidOptionsError,
    NotebookNotFoundError,
    WorkspaceReadOnlyError,
)
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.modules.notebooks.wiring_studio import StudioServices
from app.shared.actor import Actor
from app.shared.contracts.lms_blocks import (
    CoursePlanInput,
    StepDraftInput,
    build_step_content,
)
from tests.factories.notebooks import make_notebook, make_source
from tests.fakes.notebooks.llm import ScriptedLlm
from tests.fakes.notebooks.lms_apply import FakeCourseDraft
from tests.notebooks.unit.studio.helpers import SOURCE_TEXTS, generate, stored

import pytest


async def test_a_course_plan_is_generated_and_matches_the_plan_contract(
    studio: StudioServices,
    uow_factory: UowFactory,
    editor: Actor,
    workspace: Notebook,
    source: Source,
    scripted_llm: ScriptedLlm,
) -> None:
    """LMS-AI-STUDIO: request -> job -> ready plan with refs and course prompts."""
    artifact = await generate(
        studio,
        uow_factory,
        editor,
        workspace,
        ArtifactKind.COURSE_PLAN,
        {"depth": "detailed", "sections_hint": 3},
    )

    assert artifact.status is ArtifactStatus.READY
    assert artifact.content is not None
    plan = CoursePlanInput.model_validate(artifact.content)
    assert plan.sections and plan.sections[0].steps
    assert artifact.refs_index and all(
        k.startswith("S1:P") for k in artifact.refs_index
    )
    call = scripted_llm.json_requests[-1]
    assert call["schema_name"] == "nb_course_plan"
    assert "course design assistant" in call["system"]
    task = call["messages"][-1]["content"]
    assert "senior instructional designer" in task and "about 3 sections" in task


async def test_the_workspace_outline_reaches_the_plan_prompt(
    studio: StudioServices,
    uow_factory: UowFactory,
    editor: Actor,
    workspace: Notebook,
    source: Source,
    scripted_llm: ScriptedLlm,
) -> None:
    """LMS-AI-STUDIO: the draft outline is rendered into the task of the plan."""
    await generate(studio, uow_factory, editor, workspace, ArtifactKind.COURSE_PLAN)

    task = scripted_llm.json_requests[-1]["messages"][-1]["content"]
    assert task.startswith('<course title="Biology 10">')
    assert "Light reactions" in task and "Photons" in task
    assert "exactly its current title" in task


@pytest.mark.parametrize("language", ["en", "ru", "uz"])
async def test_a_lesson_draft_with_test_and_cards_is_generated_in_each_language(
    studio: StudioServices,
    uow_factory: UowFactory,
    editor: Actor,
    workspace: Notebook,
    source: Source,
    scripted_llm: ScriptedLlm,
    language: str,
) -> None:
    """LMS-AI-STUDIO: the fake model writes a believable lesson in en, ru and uz."""
    options: dict[str, Any] = {
        "include_test": True,
        "include_flashcards": True,
        "language": language,
    }

    artifact = await generate(
        studio, uow_factory, editor, workspace, ArtifactKind.LESSON_DRAFT, options
    )

    assert artifact.status is ArtifactStatus.READY and artifact.content is not None
    assert artifact.content["language"] == language
    draft = StepDraftInput.model_validate(artifact.content)
    assert [b.type for b in draft.blocks] == ["text", "flashcards", "test"]
    step = build_step_content(draft)
    assert step["blocks"][0]["markdown"].startswith("### ")
    assert "S1:P" not in step["blocks"][0]["markdown"]
    assert f"Write in {_NAMES[language]}" in scripted_llm.json_requests[-1]["system"]


_NAMES = {"en": "English", "ru": "Russian", "uz": "Uzbek"}


async def test_the_requesters_language_is_stored_in_the_options(
    studio: StudioServices, editor: Actor, workspace: Notebook, source: Source
) -> None:
    """LMS-AI-STUDIO: not the workspace owner's locale decides later in the job."""
    queued = await studio.request_artifact.execute(
        editor, workspace.id, ArtifactKind.COURSE_PLAN, {}, None
    )

    assert queued.options["language"] == "en"  # the editor's locale
    assert queued.cache_key is None


async def test_a_bad_first_answer_is_repaired_once(
    studio: StudioServices,
    uow_factory: UowFactory,
    editor: Actor,
    workspace: Notebook,
    source: Source,
    scripted_llm: ScriptedLlm,
) -> None:
    """LMS-AI-STUDIO: the problems of the first answer go back to the model."""
    scripted_llm.queue_json(
        {"title": "x", "blocks": [{"type": "text", "markdown": ""}]}
    )

    artifact = await generate(
        studio, uow_factory, editor, workspace, ArtifactKind.LESSON_DRAFT
    )

    assert artifact.status is ArtifactStatus.READY
    repair = scripted_llm.json_requests[-1]["messages"][-1]["content"]
    assert "Your previous JSON had these problems" in repair
    assert "a text block needs `markdown`" in repair


async def test_two_bad_answers_fail_the_output(
    studio: StudioServices,
    uow_factory: UowFactory,
    editor: Actor,
    workspace: Notebook,
    source: Source,
    scripted_llm: ScriptedLlm,
) -> None:
    """LMS-AI-STUDIO: after one repair the output ends as invalid."""
    bad = {"title": "x", "sections": []}
    scripted_llm.queue_json(bad)
    scripted_llm.queue_json(bad)

    artifact = await generate(
        studio, uow_factory, editor, workspace, ArtifactKind.COURSE_PLAN
    )

    assert artifact.status is ArtifactStatus.FAILED
    assert artifact.error is not None and artifact.error.code == "invalid_output"


async def test_a_quiz_in_a_workspace_knows_where_it_goes(
    studio: StudioServices,
    uow_factory: UowFactory,
    editor: Actor,
    workspace: Notebook,
    source: Source,
    scripted_llm: ScriptedLlm,
) -> None:
    """LMS-AI-STUDIO: quiz and cards get the course hint; the course kinds do not."""
    await generate(studio, uow_factory, editor, workspace, ArtifactKind.QUIZ)

    task = scripted_llm.json_requests[-1]["messages"][-1]["content"]
    assert "graded test block of the course «Biology 10»" in task
    assert "course design assistant" not in scripted_llm.json_requests[-1]["system"]


async def test_course_kinds_need_a_course_workspace(
    studio: StudioServices, uow_factory: UowFactory, editor: Actor
) -> None:
    """LMS-AI-STUDIO: a personal notebook cannot make a course plan."""
    personal = await make_notebook(uow_factory, editor.user_id, title="Mine")
    await make_source(uow_factory, personal, texts=SOURCE_TEXTS)

    for kind in (ArtifactKind.COURSE_PLAN, ArtifactKind.LESSON_DRAFT):
        with pytest.raises(InvalidOptionsError):
            await studio.request_artifact.execute(editor, personal.id, kind, {}, None)


async def test_only_course_editors_request_course_outputs(
    studio: StudioServices,
    reader: Actor,
    stranger: Actor,
    workspace: Notebook,
    source: Source,
    draft: FakeCourseDraft,
) -> None:
    """LMS-AI-STUDIO: `view_drafts` reads, a stranger finds nothing."""
    with pytest.raises(WorkspaceReadOnlyError):
        await studio.request_artifact.execute(
            reader, workspace.id, ArtifactKind.COURSE_PLAN, {}, None
        )
    with pytest.raises(NotebookNotFoundError):
        await studio.request_artifact.execute(
            stranger, workspace.id, ArtifactKind.COURSE_PLAN, {}, None
        )


async def test_the_chat_never_proposes_course_outputs(
    uow_factory: UowFactory, editor: Actor, workspace: Notebook, source: Source
) -> None:
    """LMS-AI-STUDIO: an <action> for a course kind is ignored like an unknown kind."""
    from app.modules.notebooks.domain.chat_action import split_action

    text, action = split_action(
        'Sure.\n<action>{"kind": "course_plan", "options": {}}</action>'
    )

    assert action is None
    assert "<action>" not in text


async def test_generation_row_is_readable_after_the_job(
    studio: StudioServices,
    uow_factory: UowFactory,
    editor: Actor,
    workspace: Notebook,
    source: Source,
) -> None:
    """LMS-AI-STUDIO: the stored row carries the rows' owner = the workspace owner."""
    artifact = await generate(
        studio, uow_factory, editor, workspace, ArtifactKind.LESSON_DRAFT
    )

    row = await stored(uow_factory, artifact.id)
    assert row.owner_id == workspace.owner_id
    assert row.kind is ArtifactKind.LESSON_DRAFT
