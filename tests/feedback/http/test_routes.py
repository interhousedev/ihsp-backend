"""HTTP: /v1/feedback for signed-in users, /v1/admin/feedback for administrators."""

from typing import Any

from app.interfaces.http.dependencies import get_actor
from app.interfaces.http.v1.admin_feedback import ROUTERS as ADMIN_ROUTERS
from app.interfaces.http.v1.feedback import ROUTERS
from app.shared.actor import Actor, Role
from app.shared.ids import new_id
from tests.feedback.conftest import FeedbackHarness

import pytest
from httpx import AsyncClient

FEEDBACK_KEYS = {
    "id", "kind", "area", "title", "description", "status", "source", "created_at",
    "attachments", "response_count",
}  # fmt: skip
BODY = {"kind": "bug", "area": "my", "title": "Blank", "description": "Nothing"}


class Api:
    """A client whose requests run as ``actor``."""

    def __init__(self, client: AsyncClient, actor: Actor) -> None:
        """Start as ``actor``."""
        self.client = client
        self.actor = actor


@pytest.fixture
async def api(fb: FeedbackHarness, http_client: Any) -> Api:
    """Both routers on the fake module."""
    holder: dict[str, Api] = {}
    client = await http_client(
        [*ROUTERS, *ADMIN_ROUTERS],
        {get_actor: lambda: holder["api"].actor},
        feedback=fb.services,
    )
    holder["api"] = Api(client, fb.student)
    return holder["api"]


async def test_user_submits_lists_and_reads_own(api: Api, fb: FeedbackHarness) -> None:
    """FB-01, FB-06: 201 with the contract, mine, detail, others get 404."""
    shot = fb.file(fb.student)
    created = await api.client.post(
        "/v1/feedback",
        json={**BODY, "attachment_file_ids": [str(shot.id)], "page_url": "/my/"},
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert set(body) == FEEDBACK_KEYS
    assert set(body["attachments"][0]) == {
        "file_id", "name", "mime", "size", "download_url",
    }  # fmt: skip

    mine = (await api.client.get("/v1/feedback/mine")).json()
    assert [i["id"] for i in mine["items"]] == [body["id"]]
    detail = (await api.client.get(f"/v1/feedback/{body['id']}")).json()
    assert set(detail) == FEEDBACK_KEYS | {"responses"}

    api.actor = Actor(user_id=new_id(), roles=frozenset({Role.TEACHER}))
    missing = await api.client.get(f"/v1/feedback/{body['id']}")
    assert missing.status_code == 404
    assert missing.json()["type"] == "feedback/not-found"


async def test_enums_and_limits_are_validated(api: Api) -> None:
    """FB-01: unknown kind or area, long title, 11 files answer 422."""
    for patch in (
        {"kind": "wish"},
        {"area": "kitchen"},
        {"title": "x" * 121},
        {"attachment_file_ids": [str(new_id()) for _ in range(11)]},
    ):
        response = await api.client.post("/v1/feedback", json={**BODY, **patch})
        assert response.status_code == 422, patch


async def test_rate_limit_answers_429(api: Api) -> None:
    """FB-04: the 11th item of the day."""
    for _ in range(10):
        assert (await api.client.post("/v1/feedback", json=BODY)).status_code == 201
    limited = await api.client.post("/v1/feedback", json=BODY)
    assert limited.status_code == 429
    assert limited.json()["type"] == "feedback/rate-limited"


async def test_admin_routes(api: Api, fb: FeedbackHarness) -> None:
    """FB-07: 403 for non-admins; list, detail, status and response for admins."""
    created = (await api.client.post("/v1/feedback", json=BODY)).json()
    path = f"/v1/admin/feedback/{created['id']}"
    assert (await api.client.get("/v1/admin/feedback")).status_code == 403

    api.actor = fb.admin
    page = (await api.client.get("/v1/admin/feedback", params={"kind": "bug"})).json()
    assert set(page) == {"items", "next_cursor"}
    assert set(page["items"][0]["reporter"]) == {
        "user_id", "display_name", "roles", "group_name",
    }  # fmt: skip
    bad = await api.client.get("/v1/admin/feedback", params={"status": "closed"})
    assert bad.status_code == 422

    patched = await api.client.patch(path, json={"status": "in_review"})
    assert patched.json()["status"] == "in_review"
    assert "page_url" in patched.json()

    answer = await api.client.post(
        f"{path}/responses", json={"text": "Thanks", "channels": ["telegram"]}
    )
    assert answer.status_code == 201, answer.text
    assert answer.json()["deliveries"] == [{"channel": "telegram", "status": "sent"}]
    empty = await api.client.post(
        f"{path}/responses", json={"text": "x", "channels": []}
    )
    assert empty.status_code == 422
    detail = (await api.client.get(path)).json()
    assert detail["response_count"] == 1
    assert len(detail["responses"]) == 1
