"""Broadcast routes for Administration (ADM-11, UF-ADM-08)."""

from datetime import datetime, timedelta
from typing import Any

from app.interfaces.http.dependencies import get_actor
from app.interfaces.http.v1.admin_broadcasts import ROUTERS
from app.shared.actor import Actor, Role
from tests.admin.conftest import Stack
from tests.conftest import HttpClientFactory
from tests.factories.notify import make_user
from tests.fakes.clock import FixedClock

import pytest
from httpx import AsyncClient

AUDIENCE = {"everyone": False, "roles": ["student"], "group_ids": [], "semesters": []}
INPUT = {
    "title": "Exams",
    "text": "<b>Monday</b>",
    "media_file_ids": [],
    "audience": AUDIENCE,
}


@pytest.fixture
async def client(stack: Stack, http_client: HttpClientFactory) -> AsyncClient:
    return await http_client(
        ROUTERS, overrides={get_actor: lambda: stack.actor}, admin=stack.admin
    )


async def create(client: AsyncClient, **changes: Any) -> dict[str, Any]:
    response = await client.post("/v1/admin/broadcasts", json={**INPUT, **changes})
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def test_create_returns_a_draft_with_the_contract_fields(
    client: AsyncClient, stack: Stack
) -> None:
    """ADM-11: BroadcastItem = BroadcastInput + id, status, author, stats."""
    body = await create(client)

    assert set(body) == {
        "id",
        "title",
        "text",
        "media_file_ids",
        "audience",
        "status",
        "scheduled_at",
        "created_via",
        "author",
        "stats",
        "created_at",
    }
    assert body["status"] == "draft"
    assert body["created_via"] == "ui"
    assert body["stats"] is None and body["scheduled_at"] is None
    assert body["audience"] == AUDIENCE
    assert body["author"] == {
        "id": str(stack.actor.user_id),
        "first_name": "Gulnora",
        "last_name": "Karimova",
    }


async def test_get_list_and_patch(client: AsyncClient) -> None:
    """ADM-11: read, list by status, edit a draft."""
    created = await create(client)
    bid = created["id"]

    fetched = await client.get(f"/v1/admin/broadcasts/{bid}")
    patched = await client.patch(
        f"/v1/admin/broadcasts/{bid}",
        json={"title": "Final exams", "audience": {**AUDIENCE, "semesters": [1]}},
    )
    drafts = await client.get("/v1/admin/broadcasts?status=draft")
    sent = await client.get("/v1/admin/broadcasts?status=sent")

    assert fetched.json()["id"] == bid
    assert patched.json()["title"] == "Final exams"
    assert patched.json()["text"] == "<b>Monday</b>"
    assert patched.json()["audience"]["semesters"] == [1]
    assert [i["id"] for i in drafts.json()["items"]] == [bid]
    assert sent.json() == {"items": [], "next_cursor": None}


async def test_audience_count_counts_active_recipients(
    client: AsyncClient, stack: Stack
) -> None:
    """UF-ADM-08 step 2: the number of recipients is shown."""
    stack.identity.add_user(make_user(Role.STUDENT), 1)
    stack.identity.add_user(make_user(Role.STUDENT), 2)

    response = await client.post(
        "/v1/admin/broadcasts/audience-count", json={"audience": AUDIENCE}
    )

    assert response.status_code == 200
    assert response.json() == {"count": 2}


async def test_preview_returns_204(client: AsyncClient) -> None:
    """UF-ADM-08 step 3: the preview goes to the caller's Telegram."""
    created = await create(client)

    response = await client.post(f"/v1/admin/broadcasts/{created['id']}/preview")

    assert response.status_code == 204


async def test_send_schedule_and_cancel(
    client: AsyncClient, stack: Stack, clock: FixedClock
) -> None:
    """UF-ADM-08 step 4: schedule, then cancel before it starts."""
    stack.identity.add_user(make_user(Role.STUDENT), 1)
    created = await create(client)
    at = (clock.now() + timedelta(hours=2)).isoformat()

    scheduled = await client.post(
        f"/v1/admin/broadcasts/{created['id']}/send", json={"scheduled_at": at}
    )
    cancelled = await client.post(f"/v1/admin/broadcasts/{created['id']}/cancel")
    sent_after = await client.post(f"/v1/admin/broadcasts/{created['id']}/send")

    assert scheduled.json()["status"] == "scheduled"
    assert datetime.fromisoformat(
        scheduled.json()["scheduled_at"]
    ) == clock.now() + timedelta(hours=2)
    assert cancelled.json()["status"] == "cancelled"
    assert sent_after.status_code == 409
    assert sent_after.json()["type"] == "admin/broadcast-not-sendable"


async def test_send_now_without_a_body(client: AsyncClient, stack: Stack) -> None:
    """UF-ADM-08 step 4: `{scheduled_at?}` may be left out."""
    stack.identity.add_user(make_user(Role.STUDENT), 1)
    created = await create(client)

    response = await client.post(f"/v1/admin/broadcasts/{created['id']}/send")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "sending"
    assert body["stats"] == {"total": 1, "sent": 0, "failed": 0, "blocked": 0}


async def test_sending_to_an_empty_audience_is_a_validation_error(
    client: AsyncClient,
) -> None:
    """ADM-11: nobody to send to."""
    created = await create(client)

    response = await client.post(f"/v1/admin/broadcasts/{created['id']}/send")

    assert response.status_code == 422
    assert response.json()["type"] == "admin/broadcast-empty-audience"


async def test_unknown_broadcast_is_not_found(client: AsyncClient) -> None:
    """ADM-11: 404 problem+json."""
    response = await client.get(
        "/v1/admin/broadcasts/00000000-0000-7000-8000-000000000000"
    )

    assert response.status_code == 404
    assert response.json()["type"] == "admin/broadcast-not-found"


async def test_only_administration_can_use_the_routes(
    stack: Stack, http_client: HttpClientFactory
) -> None:
    """GEN-7: a teacher gets 403."""
    teacher = Actor(user_id=stack.actor.user_id, roles=frozenset({Role.TEACHER}))
    client = await http_client(
        ROUTERS, overrides={get_actor: lambda: teacher}, admin=stack.admin
    )

    response = await client.get("/v1/admin/broadcasts")

    assert response.status_code == 403
    assert response.json()["type"] == "common/forbidden"
