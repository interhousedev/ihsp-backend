"""LMS-AI 4: the HTTP routes of course workspaces."""

from typing import Any

from app.interfaces.http.dependencies import get_actor
from app.interfaces.http.v1.notebooks import ROUTERS
from app.modules.notebooks.domain.entities import Notebook, Source
from app.modules.notebooks.wiring import NotebooksServices
from app.settings import Settings
from app.shared.actor import Actor
from tests.fakes.notebooks.lms_workspace import WorkspaceCourse

import pytest
from httpx import AsyncClient, Response


@pytest.fixture
def current(teacher: Actor) -> dict[str, Actor]:
    """The actor of the next request (replace `current["actor"]`)."""
    return {"actor": teacher}


@pytest.fixture
async def api(
    http_client: Any, services: NotebooksServices, current: dict[str, Actor]
) -> AsyncClient:
    """A client of the notebook routes whose requests run as `current["actor"]`."""
    client: AsyncClient = await http_client(
        ROUTERS, {get_actor: lambda: current["actor"]}, notebooks=services
    )
    return client


def problem(response: Response) -> str:
    """The problem type of an error response."""
    return str(response.json()["type"])


async def open_workspace(api: AsyncClient, course: WorkspaceCourse) -> Response:
    """POST /v1/notebooks/course-workspaces."""
    return await api.post(
        "/v1/notebooks/course-workspaces", json={"course_id": str(course.id)}
    )


async def test_an_editor_opens_the_workspace_once(
    api: AsyncClient, course: WorkspaceCourse
) -> None:
    """LMS-AI 4: get-or-create answers 200 with `created` the first time only."""
    first = await open_workspace(api, course)
    again = await open_workspace(api, course)

    assert (first.status_code, again.status_code) == (200, 200)
    body = first.json()
    assert set(body) == {"notebook_id", "course_id", "title", "can_write", "created"}
    assert (body["title"], body["can_write"], body["created"]) == (
        "Physics 9",
        True,
        True,
    )
    assert again.json()["created"] is False
    assert again.json()["notebook_id"] == body["notebook_id"]


@pytest.mark.parametrize("who", ["viewer", "stranger", "student"])
async def test_only_editors_create_it(
    api: AsyncClient,
    course: WorkspaceCourse,
    current: dict[str, Actor],
    request: pytest.FixtureRequest,
    who: str,
) -> None:
    """LMS-AI 4: a reader without a workspace and outsiders get 404."""
    current["actor"] = request.getfixturevalue(who)

    response = await open_workspace(api, course)

    assert response.status_code == 404
    assert problem(response) == "notebooks/not-found"


async def test_the_detail_tells_a_reader_it_may_only_read(
    api: AsyncClient,
    workspace: Notebook,
    course: WorkspaceCourse,
    current: dict[str, Actor],
    viewer: Actor,
) -> None:
    """LMS-AI 4: `NotebookDetail` has `course_id`, `can_write` and origin `course`."""
    current["actor"] = viewer

    detail = await api.get(f"/v1/notebooks/{workspace.id}")
    patched = await api.patch(f"/v1/notebooks/{workspace.id}", json={"pinned": True})

    body = detail.json()
    assert (body["origin"], body["course_id"], body["can_write"]) == (
        "course",
        str(course.id),
        False,
    )
    assert patched.status_code == 403
    assert problem(patched) == "notebooks/workspace-readonly"


async def test_course_staff_use_the_notebook_routes(
    api: AsyncClient, workspace: Notebook, ws_source: Source, current: dict[str, Actor]
) -> None:
    """LMS-AI 4: every `/v1/notebooks/{id}/...` route works for course staff."""
    base = f"/v1/notebooks/{workspace.id}"

    sources = await api.get(f"{base}/sources")
    added = await api.post(
        f"{base}/sources",
        json={"items": [{"kind": "text", "title": "Plan", "text": "Week 1."}]},
    )
    outputs = await api.post(f"{base}/artifacts", json={"kind": "mind_map"})

    assert [sources.status_code, added.status_code, outputs.status_code] == [
        200,
        201,
        202,
    ]


async def test_the_usage_of_a_workspace_is_the_course_pool(
    api: AsyncClient, workspace: Notebook, settings: Settings
) -> None:
    """LMS-AI 4: `GET /v1/notebooks/{id}/usage` shows the course staff limits."""
    response = await api.get(f"/v1/notebooks/{workspace.id}/usage")

    assert response.status_code == 200
    body = response.json()
    assert body["budget"]["day"]["limit"] == settings.limits.lms_ai_daily_tokens
    assert body["quotas"]["artifacts"]["limit"] == (
        settings.limits.lms_ai_artifacts_per_day
    )


async def test_the_course_steps_route_lists_the_draft_outline(
    api: AsyncClient, workspace: Notebook, course: WorkspaceCourse
) -> None:
    """LMS-AI 4: `{course_id, title, sections:[{id,title,steps:[{id,title}]}]}`."""
    step = course.sections[0].steps[0]

    response = await api.get(f"/v1/notebooks/{workspace.id}/course-steps")

    assert response.status_code == 200
    assert response.json() == {
        "course_id": str(course.id),
        "title": "Physics 9",
        "sections": [
            {
                "id": "s1",
                "title": "Dynamics",
                "steps": [{"id": str(step.id), "title": step.title, "added": False}],
            }
        ],
    }


async def test_a_draft_step_is_added_through_the_sources_route(
    api: AsyncClient, workspace: Notebook, course: WorkspaceCourse
) -> None:
    """LMS-AI 4: `{kind:"lms_step", course_id, step_id, draft:true}`."""
    step = course.sections[0].steps[0]
    item = {
        "kind": "lms_step",
        "course_id": str(course.id),
        "step_id": str(step.id),
        "draft": True,
    }

    response = await api.post(
        f"/v1/notebooks/{workspace.id}/sources", json={"items": [item]}
    )

    assert response.status_code == 201
    assert [i["kind"] for i in response.json()["items"]] == ["lms_step"]


async def test_the_workspace_needs_the_lms_feature(
    api: AsyncClient,
    workspace: Notebook,
    course: WorkspaceCourse,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LMS-AI 2: switched-off LMS answers like the other switched-off features."""
    monkeypatch.setattr(settings.features, "lms", False)

    opened = await open_workspace(api, course)
    detail = await api.get(f"/v1/notebooks/{workspace.id}")

    assert opened.status_code == 404
    assert problem(opened) == "notebooks/feature-disabled"
    assert detail.status_code == 404  # nobody may open a workspace now
