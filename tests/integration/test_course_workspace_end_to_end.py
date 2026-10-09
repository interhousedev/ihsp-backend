"""Course workspace over the real container: open, sources, Studio, Apply, author chat.

The whole feature in one pass (LMS-24, LMS-25, LMS-26): a course admin opens the AI
workspace of a course, adds a text source, lets Studio write a course plan with the
development LLM, applies the plan to the draft outline, writes a lesson into a step, and
talks to the author assistant, whose write call waits for the approval.
"""

from typing import Any
from uuid import UUID

from app.bootstrap.container import Container
from app.bootstrap.http_app import build_http_app
from app.bootstrap.seed.users import ADMIN_LOGIN
from app.bootstrap.seed_demo import seed
from app.interfaces.http.dependencies import get_actor
from app.shared.actor import Actor, Role
from tests.integration.conftest import ContainerFactory, IntegrationWorld

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

SYLLABUS = (
    "Mechanics for grade 10.\n\n"
    "Kinematics describes motion with position, velocity and acceleration. "
    "Dynamics explains motion with Newton's three laws: inertia, F = ma and action "
    "and reaction. Energy is conserved in a closed system; work changes energy.\n\n"
    "Practice: graphs of motion, free body diagrams and energy bar charts."
)


@pytest.fixture
async def workspace_app(
    make_container: ContainerFactory, world: IntegrationWorld
) -> tuple[FastAPI, Container]:
    """The `all` app over a container with the demo school and an LMS admin."""
    container = await make_container("all")
    await seed(container, world.credentials)
    app = build_http_app(container, process="all")
    user = await container.identity.directory.user_by_login(ADMIN_LOGIN)
    assert user is not None
    admin = Actor(user_id=user.id, roles=frozenset({Role.ADMIN, Role.LMS_ADMIN}))
    app.dependency_overrides[get_actor] = lambda: admin
    return app, container


async def _run_jobs(container: Container, world: IntegrationWorld) -> None:
    """Run the queued notebook jobs the way the worker would (sources, then outputs)."""
    seen = 0
    while seen < len(world.kicker.calls):
        name, kwargs = world.kicker.calls[seen]
        seen += 1
        if name == "notebooks.process_source":
            await container.notebooks.process_source.execute(kwargs["source_id"])
        elif name == "notebooks.generate_artifact":
            await container.notebooks.generate_artifact.execute(kwargs["artifact_id"])


async def _ready_artifact(
    client: AsyncClient,
    container: Container,
    world: IntegrationWorld,
    notebook_id: str,
    body: dict[str, Any],
) -> dict[str, Any]:
    created = await client.post(f"/v1/notebooks/{notebook_id}/artifacts", json=body)
    assert created.status_code == 202, created.text
    await _run_jobs(container, world)
    artifact = await client.get(
        f"/v1/notebooks/{notebook_id}/artifacts/{created.json()['id']}"
    )
    assert artifact.status_code == 200, artifact.text
    assert artifact.json()["status"] == "ready", artifact.json()
    result: dict[str, Any] = artifact.json()
    return result


async def test_plan_and_lesson_land_in_the_draft_of_the_course(
    workspace_app: tuple[FastAPI, Container], world: IntegrationWorld
) -> None:
    """LMS-24, LMS-25: sources -> course plan -> Apply -> lesson draft -> Apply."""
    app, container = workspace_app
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        course = await client.post(
            "/v1/lms/courses",
            json={
                "title": "Mechanics 10",
                "slug": "mechanics-10",
                "visibility": "public",
            },
        )
        assert course.status_code in (200, 201), course.text
        course_id = course.json()["id"]

        opened = await client.post(
            "/v1/notebooks/course-workspaces", json={"course_id": course_id}
        )
        assert opened.status_code in (200, 201), opened.text
        notebook_id = opened.json()["notebook_id"]
        assert opened.json()["can_write"] is True
        again = await client.post(
            "/v1/notebooks/course-workspaces", json={"course_id": course_id}
        )
        assert again.json()["notebook_id"] == notebook_id  # one workspace per course

        detail = await client.get(f"/v1/notebooks/{notebook_id}")
        assert detail.json()["course_id"] == course_id

        added = await client.post(
            f"/v1/notebooks/{notebook_id}/sources",
            json={"items": [{"kind": "text", "title": "Syllabus", "text": SYLLABUS}]},
        )
        assert added.status_code == 201, added.text
        await _run_jobs(container, world)

        plan = await _ready_artifact(
            client,
            container,
            world,
            notebook_id,
            {"kind": "course_plan", "options": {}},
        )
        assert plan["content"]["sections"], plan["content"]

        preview = await client.post(
            f"/v1/notebooks/{notebook_id}/artifacts/{plan['id']}/apply-preview", json={}
        )
        assert preview.status_code == 200, preview.text
        assert preview.json()["can_apply"] is True
        assert preview.json()["plan"]["new_sections"] >= 1

        applied = await client.post(
            f"/v1/notebooks/{notebook_id}/artifacts/{plan['id']}/apply",
            json={"add_briefs": True},
        )
        assert applied.status_code == 200, applied.text
        assert applied.json()["created_steps"]

        draft = await client.get(f"/v1/lms/courses/{course_id}/draft")
        assert draft.status_code == 200, draft.text
        titles = [section["title"] for section in draft.json()["outline"]]
        assert titles == [s["title"] for s in plan["content"]["sections"]]

        again_applied = await client.post(
            f"/v1/notebooks/{notebook_id}/artifacts/{plan['id']}/apply", json={}
        )
        assert (
            again_applied.json()["created_sections"] == []
        )  # nothing is created twice
        assert again_applied.json()["created_steps"] == []

        # A lesson for the first step of the first section.
        step_id = draft.json()["outline"][0]["steps"][0]["step_id"]
        lesson = await _ready_artifact(
            client,
            container,
            world,
            notebook_id,
            {
                "kind": "lesson_draft",
                "options": {"step_id": step_id, "include_test": True},
            },
        )
        assert lesson["content"]["blocks"]
        written = await client.post(
            f"/v1/notebooks/{notebook_id}/artifacts/{lesson['id']}/apply",
            json={"target_step_id": step_id},
        )
        assert written.status_code == 200, written.text
        step = await client.get(f"/v1/lms/steps/{step_id}/draft")
        assert step.status_code == 200, step.text
        assert step.json()["updated_via"] == "ai"
        kinds = {block["type"] for block in step.json()["content"]["blocks"]}
        assert "text" in kinds


async def test_a_stranger_does_not_see_the_workspace(
    workspace_app: tuple[FastAPI, Container],
) -> None:
    """The workspace of a course is invisible to people who are not on its staff."""
    app, container = workspace_app
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        course = await client.post(
            "/v1/lms/courses",
            json={"title": "Private", "slug": "private-course", "visibility": "invite"},
        )
        course_id = course.json()["id"]
        opened = await client.post(
            "/v1/notebooks/course-workspaces", json={"course_id": course_id}
        )
        notebook_id = opened.json()["notebook_id"]

        stranger_user = await container.identity.directory.user_by_login(
            "abdullayev.alisher"
        )
        assert stranger_user is not None
        stranger = Actor(user_id=stranger_user.id, roles=frozenset({Role.STUDENT}))
        app.dependency_overrides[get_actor] = lambda: stranger
        detail = await client.get(f"/v1/notebooks/{notebook_id}")
        listed = await client.get("/v1/notebooks")
        refused = await client.post(
            "/v1/notebooks/course-workspaces", json={"course_id": course_id}
        )
        sources = await client.get(f"/v1/notebooks/{notebook_id}/sources")

    assert detail.status_code == 404
    assert notebook_id not in {item["id"] for item in listed.json()["items"]}
    assert refused.status_code in (403, 404)
    assert sources.status_code == 404


async def test_the_author_assistant_asks_before_it_writes(
    workspace_app: tuple[FastAPI, Container],
) -> None:
    """LMS-26: an author chat is bound to the course; a student cannot start one."""
    app, container = workspace_app
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        course = await client.post(
            "/v1/lms/courses",
            json={"title": "Chemistry", "slug": "chemistry-10", "visibility": "public"},
        )
        course_id = course.json()["id"]
        chat = await client.post(
            "/v1/ai/chats", json={"assistant": "lms_author", "course_id": course_id}
        )
        assert chat.status_code in (200, 201), chat.text
        assert chat.json()["course_id"] == course_id
        listed = await client.get(
            "/v1/ai/chats", params={"assistant": "lms_author", "course_id": course_id}
        )
        assert [item["id"] for item in listed.json()["items"]] == [chat.json()["id"]]
        usage = await client.get(
            "/v1/ai/usage", params={"assistant": "lms_author", "course_id": course_id}
        )
        assert usage.status_code == 200, usage.text

        # The write waits for the approval; nothing is in the draft before it.
        turn = await client.post(
            f"/v1/ai/chats/{chat.json()['id']}/messages",
            json={"text": "Make an outline of the course about acids", "file_ids": []},
        )
        assert turn.status_code == 200, turn.text
        assert turn.json()["status"] == "awaiting_approval"
        call = next(
            call
            for message in turn.json()["new_messages"]
            for call in message["tool_calls"]
            if call["status"] == "pending_approval"
        )
        assert call["tool"] == "apply_outline"
        before = await client.get(f"/v1/lms/courses/{course_id}/draft")
        assert before.json()["outline"] == []

        approved = await client.post(
            f"/v1/ai/chats/{chat.json()['id']}/tool-calls/{call['id']}/approve"
        )
        assert approved.status_code == 200, approved.text
        after = await client.get(f"/v1/lms/courses/{course_id}/draft")
        assert len(after.json()["outline"]) == 2
        pending = await client.get(f"/v1/lms/courses/{course_id}/pending")
        assert any(step["via_ai"] for step in pending.json()["steps"])

        student_user = await container.identity.directory.user_by_login(
            "abdullayev.alisher"
        )
        assert student_user is not None
        student = Actor(user_id=student_user.id, roles=frozenset({Role.STUDENT}))
        app.dependency_overrides[get_actor] = lambda: student
        refused = await client.post(
            "/v1/ai/chats", json={"assistant": "lms_author", "course_id": course_id}
        )

    assert refused.status_code in (403, 404)
    assert UUID(chat.json()["id"])
