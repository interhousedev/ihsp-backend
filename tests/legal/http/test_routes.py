"""HTTP: public documents, the user's consent and the administrators' editor."""

from typing import Any

from app.interfaces.http.dependencies import get_actor
from app.interfaces.http.v1.legal import ROUTERS
from app.shared.actor import Actor
from tests.legal.conftest import FULL, LegalHarness

import pytest
from httpx import AsyncClient


class Api:
    """A client whose requests run as ``actor``."""

    def __init__(self, client: AsyncClient, actor: Actor) -> None:
        """Start as ``actor``."""
        self.client = client
        self.actor = actor


@pytest.fixture
async def api(legal: LegalHarness, http_client: Any) -> Api:
    """The legal routers on the fake module, as a student."""
    holder: dict[str, Api] = {}
    client = await http_client(
        ROUTERS, {get_actor: lambda: holder["api"].actor}, legal=legal.services
    )
    holder["api"] = Api(client, legal.student)
    return holder["api"]


DRAFT = {
    "title": {"uz": "Sarlavha", "ru": "Заголовок", "en": "Title"},
    "body_markdown": FULL,
    "announcement": {"en": "Changed"},
}


async def test_admin_edits_publishes_and_lists(api: Api, legal: LegalHarness) -> None:
    """403 for a student; draft, publish and the lists for an admin."""
    assert (await api.client.get("/v1/admin/legal/documents")).status_code == 403
    assert (
        await api.client.put("/v1/admin/legal/drafts/privacy", json=DRAFT)
    ).status_code == 403
    assert (
        await api.client.post("/v1/admin/legal/drafts/privacy/publish")
    ).status_code == 403

    api.actor = legal.admin
    early = await api.client.post("/v1/admin/legal/drafts/terms/publish")
    assert early.status_code == 422
    assert early.json()["type"] == "legal/no-draft"

    saved = await api.client.put("/v1/admin/legal/drafts/privacy", json=DRAFT)
    assert saved.status_code == 200
    body = saved.json()
    assert body["status"] == "draft" and body["version"] == 1
    assert set(body) == {
        "id", "kind", "version", "status", "title", "body_markdown",
        "announcement", "app_scope", "created_at", "updated_at", "published_at",
        "published_by",
    }  # fmt: skip

    await api.client.put(
        "/v1/admin/legal/drafts/terms",
        json={"title": {"en": "T"}, "body_markdown": {}, "announcement": None},
    )
    incomplete = await api.client.post("/v1/admin/legal/drafts/terms/publish")
    assert incomplete.status_code == 422
    assert incomplete.json()["type"] == "legal/incomplete"

    published = await api.client.post("/v1/admin/legal/drafts/privacy/publish")
    assert published.json()["status"] == "published"
    assert published.json()["published_by"] == str(legal.admin.user_id)

    listing = (await api.client.get("/v1/admin/legal/documents")).json()
    assert {(d["kind"], d["status"]) for d in listing["items"]} == {
        ("privacy", "published"),
        ("terms", "draft"),
    }
    counts = (await api.client.get("/v1/admin/legal/acceptances")).json()
    assert counts["items"] == [
        {"kind": "privacy", "app_scope": "global", "version": 1, "accepted_count": 0}
    ]


async def test_public_documents(api: Api, legal: LegalHarness) -> None:
    """Published texts are public, in the asked locale; drafts are not."""
    assert (await api.client.get("/v1/legal/documents")).json() == {"items": []}
    missing = await api.client.get("/v1/legal/documents/privacy")
    assert missing.status_code == 404
    assert missing.json()["type"] == "legal/not-found"

    await legal.services.save_draft.execute(
        "privacy",
        title=DRAFT["title"],
        body_markdown=DRAFT["body_markdown"],
        announcement=DRAFT["announcement"],
    )
    assert (await api.client.get("/v1/legal/documents/privacy")).status_code == 404
    await legal.services.publish.execute("privacy", actor_id=legal.admin.user_id)

    doc = (await api.client.get("/v1/legal/documents/privacy?locale=uz")).json()
    assert doc["title"] == "Sarlavha" and doc["locale"] == "uz"
    assert doc["announcement"] is None
    assert set(doc) == {
        "kind", "version", "locale", "title", "body_markdown", "announcement",
        "app_scope", "published_at",
    }  # fmt: skip
    en = (await api.client.get("/v1/legal/documents", params={"locale": "en"})).json()
    assert [d["announcement"] for d in en["items"]] == ["Changed"]
    bad = await api.client.get("/v1/legal/documents/privacy?locale=de")
    assert bad.status_code == 422


async def test_user_sees_pending_and_accepts(api: Api, legal: LegalHarness) -> None:
    """Pending lists current documents; accepting clears them; stale is 409."""
    await legal.publish("privacy")
    pending = (await api.client.get("/v1/me/legal/pending")).json()
    [item] = pending["items"]
    assert item["kind"] == "privacy" and item["previously_accepted_version"] is None

    await legal.publish("privacy")
    stale = await api.client.post(
        "/v1/me/legal/accept", json={"items": [{"kind": "privacy", "version": 1}]}
    )
    assert stale.status_code == 409
    assert stale.json()["type"] == "legal/stale-version"

    ok = await api.client.post(
        "/v1/me/legal/accept",
        json={"items": [{"kind": "privacy", "version": 2}]},
    )
    assert ok.status_code == 200 and ok.json() == {"items": []}
    assert (await api.client.get("/v1/me/legal/pending")).json() == {"items": []}
    assert len(legal.store.acceptances) == 1

    empty = await api.client.post("/v1/me/legal/accept", json={"items": []})
    assert empty.status_code == 422
