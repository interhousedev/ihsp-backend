"""HTTP: /v1/admin/ai/requests and the prompt versions and diff routes."""

from types import SimpleNamespace
from typing import Any
from uuid import uuid4

from app.interfaces.http.dependencies import get_actor
from app.interfaces.http.v1.admin_ai.router import router
from app.modules.ai.application.prompt_registry import PromptAdmin, PromptRegistry
from app.modules.ai.application.publish_requests import RequestPublisher
from app.modules.ai.application.request_admin import RequestAdmin
from app.modules.ai.domain.prompt_registry import PromptSlot
from app.modules.ai.domain.requests import AiRequestSpec
from app.shared.actor import Actor, Role
from tests.fakes.ai.requests import (
    FakePromptDefaults,
    FakePromptVersions,
    FakePublishUnit,
    FakeRequests,
)
from tests.fakes.clock import FixedClock

import pytest
from httpx import AsyncClient

SLOT = PromptSlot(
    "studio_quiz", "studio", "Quiz", "Write in {language}.", template=True
)
SPEC = AiRequestSpec(
    id="notebooks.studio_quiz.generate",
    owner_app="notebooks",
    task="studio_quiz",
    template=SLOT,
    args_schema={"type": "object", "required": ["language"]},
    summary="Quiz batch",
)


class Loader:
    """No stored versions in the cache."""

    async def active(self) -> list:
        """Nothing."""
        return []


@pytest.fixture
def current() -> dict[str, Actor]:
    """The actor the next request runs as."""
    return {"actor": Actor(user_id=uuid4(), roles=frozenset({Role.ADMIN}))}


@pytest.fixture
async def client(http_client: Any, current: dict[str, Actor]) -> AsyncClient:
    """A client over the routes with in-memory stores and a published request."""
    prompts, defaults, requests = (
        FakePromptVersions(),
        FakePromptDefaults(),
        FakeRequests(),
    )

    def unit() -> FakePublishUnit:
        return FakePublishUnit(prompts, defaults, requests, [])

    await RequestPublisher(unit, FixedClock()).publish([SLOT], [SPEC])
    services = SimpleNamespace(
        request_admin=RequestAdmin(unit),
        admin=PromptAdmin(PromptRegistry([SLOT], Loader()), unit, FixedClock()),
    )
    return await http_client(
        [router],
        {get_actor: lambda: current["actor"]},
        ai=SimpleNamespace(prompts=services),
    )


async def test_list_and_get_a_request(client: AsyncClient) -> None:
    """The list and the item have the same shape."""
    listed = (await client.get("/v1/admin/ai/requests")).json()
    one = await client.get(f"/v1/admin/ai/requests/{SPEC.id}")

    assert one.status_code == 200
    assert listed == {"items": [one.json()]}
    item = one.json()
    assert item["id"] == SPEC.id and item["owner_app"] == "notebooks"
    assert item["pipeline"] == "studio" and item["template_id"] == "studio_quiz/studio"
    assert item["args_schema"]["required"] == ["language"]
    assert item["active_version"] == 0 and item["code_changed_since_active"] is False
    assert item["retired"] is False and item["published_at"]


async def test_filters_and_missing_request(client: AsyncClient) -> None:
    """A filter that matches nothing is empty; an unknown id is a 404 problem."""
    none = await client.get("/v1/admin/ai/requests", params={"owner_app": "lms"})
    missing = await client.get("/v1/admin/ai/requests/notebooks.nothing.here")

    assert none.json() == {"items": []}
    assert missing.status_code == 404
    assert missing.headers["content-type"].startswith("application/problem+json")


async def test_versions_and_diff_follow_the_admin_edits(
    client: AsyncClient, current: dict[str, Actor]
) -> None:
    """The version list hides the text; the diff compares versions."""
    state = client._transport.app.state  # type: ignore[attr-defined]
    prompts = state.container.ai.prompts
    admin = prompts.admin
    await admin.put_version(
        current["actor"], "studio_quiz", "studio", text="One {language}."
    )
    await admin.put_version(
        current["actor"], "studio_quiz", "studio", text="Two {language}."
    )

    versions = await client.get("/v1/admin/ai/prompts/studio_quiz/studio/versions")
    diff = await client.get("/v1/admin/ai/prompts/studio_quiz/studio/diff")
    from_builtin = await client.get(
        "/v1/admin/ai/prompts/studio_quiz/studio/diff", params={"from": 0, "to": 1}
    )
    bad = await client.get(
        "/v1/admin/ai/prompts/studio_quiz/studio/diff", params={"from": 2, "to": 1}
    )
    unknown = await client.get(
        "/v1/admin/ai/prompts/studio_quiz/studio/diff", params={"from": 0, "to": 9}
    )

    items = versions.json()["items"]
    assert [i["version"] for i in items] == [2, 1]
    assert items[0]["source"] == "admin" and items[0]["active"] is True
    assert items[0]["has_diff"] is True and "text" not in items[0]
    assert items[0]["chars"] == len("Two {language}.")
    body = diff.json()
    assert (body["from_version"], body["to_version"]) == (1, 2)
    assert "-One {language}." in body["diff"] and "+Two {language}." in body["diff"]
    assert from_builtin.json()["from_version"] == 0
    assert bad.status_code == 422
    assert unknown.status_code == 404


async def test_non_admins_are_refused(
    client: AsyncClient, current: dict[str, Actor]
) -> None:
    """Only administrators read the registry."""
    current["actor"] = Actor(user_id=uuid4(), roles=frozenset({Role.STUDENT}))

    refused = await client.get("/v1/admin/ai/requests")

    assert refused.status_code == 403
