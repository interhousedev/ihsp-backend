"""HTTP: admin POST/GET /v1/admin/students/{user_id}/sync (re-sync one student)."""

import uuid
from types import SimpleNamespace
from typing import Any

from app.interfaces.http.dependencies import get_actor
from app.interfaces.http.v1.admin_student_sync import ROUTERS
from app.shared.actor import Role
from tests.academic.schedule.env import Env


async def _client(http_client: Any, env: Env, actor: Any) -> Any:
    return await http_client(
        ROUTERS,
        {get_actor: lambda: actor},
        academic=SimpleNamespace(emis_import=env.emis_import),
    )


async def test_admin_queues_a_sync_and_reads_its_state(
    http_client: Any, env: Env, make_actor: Any
) -> None:
    """202 with the queued job, GET answers the same state, kick carries the user."""
    client = await _client(http_client, env, make_actor(Role.ADMIN))
    student = uuid.uuid4()
    path = f"/v1/admin/students/{student}/sync"

    before = await client.get(path)
    posted = await client.post(path)
    after = await client.get(path)

    assert before.status_code == 200 and before.json() is None
    assert posted.status_code == 202
    assert posted.json()["status"] == "pending"
    assert posted.json()["user_id"] == str(student)
    assert posted.json()["finished_at"] is None
    assert after.json() == posted.json()
    assert env.kicker.calls[-1] == (
        "academic.run_student_sync",
        {"user_id": str(student)},
    )


async def test_a_second_click_while_pending_queues_nothing(
    http_client: Any, env: Env, make_actor: Any
) -> None:
    """Idempotent: the pending job is returned and no second kick is sent."""
    client = await _client(http_client, env, make_actor(Role.ADMIN))
    path = f"/v1/admin/students/{uuid.uuid4()}/sync"
    first = await client.post(path)

    second = await client.post(path)

    assert second.status_code == 202
    assert second.json() == first.json()
    assert env.kicker.names().count("academic.run_student_sync") == 1


async def test_a_finished_failure_is_queued_again(
    http_client: Any, env: Env, make_actor: Any
) -> None:
    """A failed job is reset to pending and kicked once more."""
    client = await _client(http_client, env, make_actor(Role.ADMIN))
    student = uuid.uuid4()
    path = f"/v1/admin/students/{student}/sync"
    await client.post(path)
    job = await env.emis_import.sync_jobs.claim(student, env.clock.now())
    assert job is not None
    await env.emis_import.sync_jobs.fail(
        student,
        env.clock.now(),
        attempt=job.attempts,
        error="RuntimeError: boom",
        next_attempt_at=None,
    )

    response = await client.post(path)

    assert response.json()["status"] == "pending"
    assert response.json()["last_error"] is None
    assert env.kicker.names().count("academic.run_student_sync") == 2


async def test_a_running_sync_is_returned_unchanged(
    http_client: Any, env: Env, make_actor: Any
) -> None:
    """Idempotent while running: the running state comes back, nothing is queued."""
    client = await _client(http_client, env, make_actor(Role.ADMIN))
    student = uuid.uuid4()
    path = f"/v1/admin/students/{student}/sync"
    await client.post(path)
    await env.emis_import.sync_jobs.claim(student, env.clock.now())

    response = await client.post(path)

    assert response.json()["status"] == "running"
    assert response.json()["attempts"] == 1
    assert env.kicker.names().count("academic.run_student_sync") == 1


async def test_non_admins_are_refused(
    http_client: Any, env: Env, make_actor: Any
) -> None:
    """Students and teachers get 403 on both the POST and the GET."""
    path = f"/v1/admin/students/{uuid.uuid4()}/sync"
    for role in (Role.STUDENT, Role.TEACHER):
        client = await _client(http_client, env, make_actor(role))

        posted = await client.post(path)
        read = await client.get(path)

        assert posted.status_code == 403
        assert read.status_code == 403
    assert env.kicker.names().count("academic.run_student_sync") == 0
