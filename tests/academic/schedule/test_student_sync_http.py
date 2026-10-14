"""HTTP: POST /v1/me/sync queues the student's full sync, GET reads its state."""

from types import SimpleNamespace
from typing import Any

from app.interfaces.http.dependencies import get_actor
from app.interfaces.http.v1.me_sync import ROUTERS
from app.shared.actor import Role
from tests.academic.schedule.env import Env


async def _client(http_client: Any, env: Env, actor: Any) -> Any:
    return await http_client(
        ROUTERS,
        {get_actor: lambda: actor},
        academic=SimpleNamespace(emis_import=env.emis_import),
    )


async def test_the_button_queues_a_sync_and_the_page_reads_it(
    http_client: Any, env: Env, make_actor: Any
) -> None:
    """202 with the queued state; GET answers the same state."""
    actor = make_actor(Role.STUDENT)
    client = await _client(http_client, env, actor)

    before = await client.get("/v1/me/sync")
    posted = await client.post("/v1/me/sync")
    after = await client.get("/v1/me/sync")

    assert before.status_code == 200 and before.json() is None
    assert posted.status_code == 202
    assert posted.json()["status"] == "queued"
    assert posted.json()["finished_at"] is None
    assert after.json() == posted.json()
    assert env.kicker.calls[-1] == (
        "academic.sync_student_all",
        {"user_id": str(actor.user_id), "with_marks": True},
    )


async def test_a_second_click_within_ten_minutes_answers_429(
    http_client: Any, env: Env, make_actor: Any
) -> None:
    """Rate limited per student."""
    client = await _client(http_client, env, make_actor(Role.STUDENT))
    await client.post("/v1/me/sync")

    response = await client.post("/v1/me/sync")

    assert response.status_code == 429


async def test_a_teacher_may_not_ask(
    http_client: Any, env: Env, make_actor: Any
) -> None:
    """Students only."""
    client = await _client(http_client, env, make_actor(Role.TEACHER))

    response = await client.post("/v1/me/sync")

    assert response.status_code == 403
