"""LMS-AI-STUDIO: HTTP `apply-preview` and `apply` of a course workspace output."""

from typing import Any, cast
from uuid import UUID

from app.interfaces.http.dependencies import get_actor
from app.interfaces.http.v1.notebooks import ROUTERS
from app.interfaces.http.v1.notebooks.router_studio import router
from app.modules.notebooks.domain.entities import Notebook
from app.modules.notebooks.domain.enums import ArtifactKind
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.modules.notebooks.wiring import NotebooksServices, build
from app.modules.notebooks.wiring_studio import LmsApplyPorts
from app.shared.actor import Actor
from app.shared.contracts.academic import ClassworkQueries, ScheduleQueries
from app.shared.contracts.ai import AiQueries
from app.shared.contracts.files import FilesApi
from app.shared.contracts.flashcards import FlashcardsApi
from app.shared.contracts.identity import IdentityDirectory
from app.shared.contracts.links import LinksApi
from app.shared.contracts.lms import (
    LmsDraftCommands,
    LmsQueries,
    LmsSourceReader,
    LmsWorkspaceCommands,
)
from app.shared.wiring import ModuleDeps
from tests.fakes.ai.contracts import FakeIdentity
from tests.fakes.notebooks.llm import ScriptedLlm
from tests.fakes.notebooks.lms_apply import FakeCourseDraft
from tests.fakes.notebooks.world import World
from tests.notebooks.course_studio.support import DECK, LESSON, PLAN, QUIZ, ready

import pytest
from fastapi import FastAPI
from httpx import AsyncClient, Response


@pytest.fixture
def world() -> World:
    """Empty fakes of the other modules."""
    return World()


@pytest.fixture
def services(
    module_deps: ModuleDeps,
    scripted_llm: ScriptedLlm,
    identity: FakeIdentity,
    world: World,
    draft: FakeCourseDraft,
) -> NotebooksServices:
    """The whole module with the course draft as LMS workspace and apply ports."""
    return build(
        module_deps,
        llm=scripted_llm,
        identity=cast(IdentityDirectory, identity),
        files=cast(FilesApi, world.files),
        ai=cast(AiQueries, world.chats),
        links=cast(LinksApi, world.links),
        schedule=cast(ScheduleQueries, world.schedule),
        flashcards=cast(FlashcardsApi, world.flashcards),
        lms=cast(LmsSourceReader, world.lms),
        classwork=cast(ClassworkQueries, world.classwork),
        terms=world.terms,
        workspace=draft,
        lms_apply=LmsApplyPorts(
            workspace=cast(LmsWorkspaceCommands, draft),
            queries=cast(LmsQueries, draft),
            drafts=cast(LmsDraftCommands, draft),
        ),
    )


@pytest.fixture
def current(editor: Actor) -> dict[str, Actor]:
    """The actor of the next request."""
    return {"actor": editor}


@pytest.fixture
async def api(
    http_client: Any, services: NotebooksServices, current: dict[str, Actor]
) -> AsyncClient:
    """A client of the notebook routes whose requests run as `current["actor"]`."""
    client: AsyncClient = await http_client(
        ROUTERS, {get_actor: lambda: current["actor"]}, notebooks=services
    )
    return client


def url(notebook: Notebook, artifact_id: UUID, action: str) -> str:
    return f"/v1/notebooks/{notebook.id}/artifacts/{artifact_id}/{action}"


def problem_type(response: Response) -> str:
    assert response.headers["content-type"].startswith("application/problem+json")
    return str(response.json()["type"])


async def test_plan_preview_answers_with_the_outline_diff(
    api: AsyncClient, uow_factory: UowFactory, workspace: Notebook
) -> None:
    """LMS-AI-STUDIO: apply-preview returns kind, can_apply, problems and the plan."""
    artifact = await ready(uow_factory, workspace, ArtifactKind.COURSE_PLAN, PLAN)

    response = await api.post(url(workspace, artifact.id, "apply-preview"), json={})

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"kind", "can_apply", "problems", "notes", "plan", "step"}
    assert body["kind"] == "course_plan" and body["can_apply"] is True
    assert body["step"] is None
    plan = body["plan"]
    assert (plan["new_sections"], plan["new_steps"], plan["existing_steps"]) == (
        1,
        2,
        1,
    )
    assert plan["sections"][0]["steps"][0]["step_id"] is not None
    assert plan["sections"][1] == {
        "title": "Calvin cycle",
        "section_id": None,
        "action": "new",
        "steps": [{"title": "Carbon fixation", "step_id": None, "action": "new"}],
    }


async def test_plan_apply_answers_with_what_was_created(
    api: AsyncClient,
    uow_factory: UowFactory,
    workspace: Notebook,
    draft: FakeCourseDraft,
) -> None:
    """LMS-AI-STUDIO: apply returns the created sections and steps."""
    artifact = await ready(uow_factory, workspace, ArtifactKind.COURSE_PLAN, PLAN)

    response = await api.post(
        url(workspace, artifact.id, "apply"), json={"add_briefs": True}
    )

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "kind",
        "created_sections",
        "created_steps",
        "step_id",
        "lock_version",
        "draft_seq",
    }
    assert [s["title"] for s in body["created_sections"]] == ["Calvin cycle"]
    assert [s["title"] for s in body["created_steps"]] == [
        "Pigments",
        "Carbon fixation",
    ]
    assert body["step_id"] is None and body["draft_seq"] == draft.draft_seq


async def test_lesson_preview_and_apply_round_trip_the_lock_version(
    api: AsyncClient,
    uow_factory: UowFactory,
    workspace: Notebook,
    draft: FakeCourseDraft,
) -> None:
    """LMS-AI-STUDIO: the preview's lock goes back in the apply body."""
    photons = next(s for s in draft.steps.values() if s.title == "Photons")
    artifact = await ready(uow_factory, workspace, ArtifactKind.LESSON_DRAFT, LESSON)
    target = {"target_step_id": str(photons.id)}

    preview = (
        await api.post(url(workspace, artifact.id, "apply-preview"), json=target)
    ).json()
    applied = await api.post(
        url(workspace, artifact.id, "apply"),
        json={**target, "lock_version": preview["step"]["lock_version"]},
    )

    assert preview["step"]["mode"] == "replace"
    assert preview["step"]["current_blocks"] == []
    assert [b["type"] for b in preview["step"]["new_blocks"]] == ["text", "flashcards"]
    assert preview["step"]["new_blocks"][0]["markdown"].startswith("### Goal")
    assert applied.status_code == 200
    assert applied.json()["lock_version"] == 2 and applied.json()["step_id"] == str(
        photons.id
    )


async def test_an_edited_draft_in_the_body_is_applied_to_a_new_step(
    api: AsyncClient,
    uow_factory: UowFactory,
    workspace: Notebook,
    draft: FakeCourseDraft,
) -> None:
    """LMS-AI-STUDIO: `draft` is validated with the contract models."""
    artifact = await ready(uow_factory, workspace, ArtifactKind.LESSON_DRAFT, LESSON)
    body = {
        "target_section_id": "sec-1",
        "draft": {
            "title": "By hand",
            "blocks": [{"type": "text", "markdown": "Hello."}],
        },
    }

    response = await api.post(url(workspace, artifact.id, "apply"), json=body)

    assert response.status_code == 200
    assert response.json()["created_steps"][0]["title"] == "By hand"
    assert any(s.title == "By hand" for s in draft.steps.values())


@pytest.mark.parametrize(
    "body",
    [
        {"mode": "merge"},
        {"plan": {"sections": []}},
        {"draft": {"title": "x", "blocks": [{"type": "poem"}]}},
        {"lock_version": -1},
        {"target_step_id": "not-a-uuid"},
    ],
)
async def test_a_malformed_body_is_a_validation_error(
    api: AsyncClient, uow_factory: UowFactory, workspace: Notebook, body: dict[str, Any]
) -> None:
    """LMS-AI-STUDIO: the schemas refuse what the contract models refuse."""
    artifact = await ready(uow_factory, workspace, ArtifactKind.COURSE_PLAN, PLAN)

    for action in ("apply-preview", "apply"):
        response = await api.post(url(workspace, artifact.id, action), json=body)
        assert response.status_code == 422
        assert problem_type(response) == "common/request-validation"


async def test_quiz_and_deck_previews_show_blocks_and_notes(
    api: AsyncClient,
    uow_factory: UowFactory,
    workspace: Notebook,
    draft: FakeCourseDraft,
) -> None:
    """LMS-AI-STUDIO: a quiz turns into a test block and says what was reduced."""
    photons = next(s for s in draft.steps.values() if s.title == "Photons")
    quiz = await ready(uow_factory, workspace, ArtifactKind.QUIZ, QUIZ)
    deck = await ready(uow_factory, workspace, ArtifactKind.FLASHCARDS, DECK)
    target = {"target_step_id": str(photons.id)}

    quiz_view = (
        await api.post(url(workspace, quiz.id, "apply-preview"), json=target)
    ).json()
    deck_view = (
        await api.post(url(workspace, deck.id, "apply-preview"), json=target)
    ).json()

    assert quiz_view["step"]["mode"] == "append"
    block = quiz_view["step"]["new_blocks"][0]
    assert block["type"] == "test" and len(block["questions"]) == 2
    assert block["questions"][0]["options"][0]["correct"] is True
    assert quiz_view["notes"] and "true/false" in quiz_view["notes"][0]
    assert deck_view["step"]["new_blocks"][0]["cards"][0]["front"] == "Pigment?"


async def test_a_stale_lock_is_409_and_a_missing_target_is_a_problem(
    api: AsyncClient,
    uow_factory: UowFactory,
    workspace: Notebook,
    draft: FakeCourseDraft,
) -> None:
    """LMS-AI-STUDIO: 409 for a changed draft; the preview explains a missing target."""
    photons = next(s for s in draft.steps.values() if s.title == "Photons")
    photons.lock_version = 4
    artifact = await ready(uow_factory, workspace, ArtifactKind.LESSON_DRAFT, LESSON)

    stale = await api.post(
        url(workspace, artifact.id, "apply"),
        json={"target_step_id": str(photons.id), "lock_version": 1},
    )
    no_target = await api.post(url(workspace, artifact.id, "apply-preview"), json={})
    refused = await api.post(url(workspace, artifact.id, "apply"), json={})

    assert stale.status_code == 409
    assert no_target.json()["can_apply"] is False and no_target.json()["problems"]
    assert refused.status_code == 422
    assert problem_type(refused) == "notebooks/invalid-options"


async def test_permissions_map_to_403_and_404(
    api: AsyncClient,
    current: dict[str, Actor],
    uow_factory: UowFactory,
    reader: Actor,
    stranger: Actor,
    workspace: Notebook,
) -> None:
    """LMS-AI-STUDIO: `view_drafts` may not apply; a stranger finds nothing."""
    artifact = await ready(uow_factory, workspace, ArtifactKind.COURSE_PLAN, PLAN)

    current["actor"] = reader
    read_only = await api.post(url(workspace, artifact.id, "apply"), json={})
    current["actor"] = stranger
    unknown = await api.post(url(workspace, artifact.id, "apply-preview"), json={})

    assert read_only.status_code == 403
    assert problem_type(read_only) == "notebooks/workspace-readonly"
    assert unknown.status_code == 404
    assert problem_type(unknown) == "notebooks/not-found"


async def test_the_openapi_lists_both_routes_with_typed_blocks() -> None:
    """LMS-AI-STUDIO: the generated client knows the bodies and the block shapes."""
    app = FastAPI()
    app.include_router(router)
    spec = app.openapi()

    paths = spec["paths"]
    one = "/v1/notebooks/{notebook_id}/artifacts/{artifact_id}"
    assert f"{one}/apply-preview" in paths and f"{one}/apply" in paths
    schemas = spec["components"]["schemas"]
    assert {"ApplyBody", "ApplyPreviewResponse", "ApplyResultResponse"} <= set(schemas)
    assert set(schemas["StepPreviewResponse"]["properties"]) == {
        "step_id",
        "title",
        "lock_version",
        "mode",
        "current_blocks",
        "new_blocks",
    }
    assert "audio" not in str(spec)
