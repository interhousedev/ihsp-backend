"""Connectors and pipeline routes over HTTP, on real SQL repositories (admin only)."""

from types import SimpleNamespace

from app.interfaces.http.dependencies import get_actor
from app.interfaces.http.v1.admin_ai.connectors import router as connectors_router
from app.modules.ai.application.connectors import ConnectorAdmin, PipelineAdmin
from app.modules.ai.application.routing import RouteService
from app.modules.ai.application.tracing_admin import TracingAdmin
from app.modules.ai.infrastructure.connector_clients import EnvConnectorRuntime
from app.modules.ai.infrastructure.connector_store import (
    SqlConnectorUnitOfWork,
    SqlRoutingLoader,
)
from app.modules.ai.infrastructure.fake_llm import FakeLlmGateway
from app.modules.ai.infrastructure.orm.connector import ConnectorRow
from app.modules.ai.infrastructure.orm.pipeline_route import PipelineRouteRow
from app.modules.ai.wiring import ConnectorServices
from app.settings import Settings
from app.shared.actor import Actor, Role
from app.shared.db.uow_testing import noop_audit_writer, noop_outbox_writer
from app.shared.ids import new_id
from tests.conftest import HttpClientFactory
from tests.fakes.ai_connectors import FakeSecrets
from tests.fakes.clock import FixedClock

import pytest
from fastapi import APIRouter
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

PREFIX = "/v1/admin/ai"
KEY = "sk-live-0123456789abcdef"
ADMIN = Actor(user_id=new_id(), roles=frozenset({Role.ADMIN}))
GROQ = {
    "id": "groq",
    "kind": "openai_compatible",
    "title": "Groq",
    "base_url": "https://api.groq.com/openai/v1",
    "api_key": KEY,
}


class World(SimpleNamespace):
    """What a test needs besides the client."""

    secrets: FakeSecrets
    sessionmaker: async_sessionmaker[AsyncSession]


@pytest.fixture
def world(sessionmaker_in_tx: async_sessionmaker[AsyncSession]) -> World:
    return World(secrets=FakeSecrets(), sessionmaker=sessionmaker_in_tx)


def _services(
    settings: Settings,
    clock: FixedClock,
    sessionmaker: async_sessionmaker[AsyncSession],
    secrets: FakeSecrets,
) -> ConnectorServices:
    runtime = EnvConnectorRuntime(settings, secrets, llm=FakeLlmGateway(), search=None)
    routing = RouteService(settings, SqlRoutingLoader(sessionmaker), runtime)

    def make_uow() -> SqlConnectorUnitOfWork:
        return SqlConnectorUnitOfWork(
            sessionmaker, noop_outbox_writer, noop_audit_writer
        )

    return ConnectorServices(
        routing=routing,
        connectors=ConnectorAdmin(
            make_uow, secrets, runtime, routing, allow_plain_local_urls=False
        ),
        pipelines=PipelineAdmin(make_uow, runtime, routing, clock),
        tracing=TracingAdmin(
            make_uow,
            secrets,
            routing,
            clock,
            env_host="https://cloud.langfuse.com",
            env_configured=False,
            capture_default=False,
            allow_plain_local_urls=False,
        ),
    )


async def _client(
    http_client: HttpClientFactory,
    settings: Settings,
    clock: FixedClock,
    world: World,
    actor: Actor = ADMIN,
) -> AsyncClient:
    parent = APIRouter(prefix=PREFIX)
    parent.include_router(connectors_router)
    services = _services(settings, clock, world.sessionmaker, world.secrets)
    return await http_client(
        [parent],
        overrides={get_actor: lambda: actor},
        ai=SimpleNamespace(connectors=services),
    )


@pytest.fixture
async def client(
    http_client: HttpClientFactory, settings: Settings, clock: FixedClock, world: World
) -> AsyncClient:
    return await _client(http_client, settings, clock, world)


async def test_the_list_has_the_built_in_connectors_and_the_kinds(
    client: AsyncClient,
) -> None:
    response = await client.get(f"{PREFIX}/connectors")

    assert response.status_code == 200
    body = response.json()
    assert [i["id"] for i in body["items"]] == ["openrouter", "anthropic", "exa"]
    assert body["kinds"] == ["openrouter", "anthropic", "openai_compatible", "exa"]
    first = body["items"][0]
    assert (first["builtin"], first["source"]) == (True, "env")
    assert set(first) == {
        "id",
        "kind",
        "title",
        "base_url",
        "enabled",
        "has_secret",
        "secret_last4",
        "builtin",
        "source",
    }


async def test_adding_a_connector_stores_a_row_and_a_vault_secret_but_returns_no_key(
    client: AsyncClient, world: World
) -> None:
    response = await client.post(f"{PREFIX}/connectors", json=GROQ)

    assert response.status_code == 201
    body = response.json()
    assert (body["id"], body["has_secret"], body["secret_last4"]) == (
        "groq",
        True,
        "cdef",
    )
    assert KEY not in response.text
    assert world.secrets.store["groq"]["api_key"] == KEY
    async with world.sessionmaker() as session:
        row = await session.scalar(
            select(ConnectorRow).where(ConnectorRow.id == "groq")
        )
    assert row is not None and row.has_secret and row.secret_last4 == "cdef"
    assert KEY not in repr(row.__dict__)
    listed = (await client.get(f"{PREFIX}/connectors")).json()["items"]
    assert [i["id"] for i in listed] == ["openrouter", "anthropic", "exa", "groq"]
    assert KEY not in (await client.get(f"{PREFIX}/connectors")).text


async def test_a_duplicate_and_bad_input_are_refused(client: AsyncClient) -> None:
    assert (await client.post(f"{PREFIX}/connectors", json=GROQ)).status_code == 201

    duplicate = await client.post(f"{PREFIX}/connectors", json=GROQ)
    bad_slug = await client.post(f"{PREFIX}/connectors", json={**GROQ, "id": "Bad Id"})
    no_url = await client.post(
        f"{PREFIX}/connectors", json={**GROQ, "id": "nourl", "base_url": None}
    )
    plain = await client.post(
        f"{PREFIX}/connectors",
        json={**GROQ, "id": "plain", "base_url": "http://x.example/v1"},
    )
    extra = await client.post(f"{PREFIX}/connectors", json={**GROQ, "id": "z", "x": 1})

    assert (duplicate.status_code, duplicate.json()["type"]) == (
        409,
        "connector_exists",
    )
    assert (bad_slug.status_code, bad_slug.json()["type"]) == (422, "validation_error")
    assert (no_url.status_code, no_url.json()["type"]) == (422, "validation_error")
    assert (plain.status_code, plain.json()["type"]) == (422, "validation_error")
    assert extra.status_code == 422


async def test_a_dead_vault_answers_503_and_leaves_no_row(
    client: AsyncClient, world: World
) -> None:
    world.secrets.available = False

    response = await client.post(f"{PREFIX}/connectors", json=GROQ)

    assert response.status_code == 503
    assert response.json()["type"] == "connector_vault_unavailable"
    async with world.sessionmaker() as session:
        assert await session.scalar(select(ConnectorRow)) is None


async def test_patching_a_built_in_adds_an_override_and_delete_removes_it(
    client: AsyncClient,
) -> None:
    patched = await client.patch(
        f"{PREFIX}/connectors/openrouter", json={"enabled": False}
    )

    assert patched.status_code == 200
    assert (patched.json()["source"], patched.json()["enabled"]) == ("db", False)
    assert (await client.delete(f"{PREFIX}/connectors/openrouter")).status_code == 204
    items = (await client.get(f"{PREFIX}/connectors")).json()["items"]
    assert (items[0]["source"], items[0]["enabled"]) == ("env", True)
    assert (await client.delete(f"{PREFIX}/connectors/openrouter")).status_code == 204


async def test_patch_and_delete_of_an_unknown_connector_are_404(
    client: AsyncClient,
) -> None:
    patched = await client.patch(f"{PREFIX}/connectors/nope", json={"title": "x"})
    deleted = await client.delete(f"{PREFIX}/connectors/nope")

    assert (patched.status_code, patched.json()["type"]) == (404, "connector_not_found")
    assert deleted.status_code == 404


async def test_patching_rotates_the_key(client: AsyncClient, world: World) -> None:
    await client.post(f"{PREFIX}/connectors", json=GROQ)

    response = await client.patch(
        f"{PREFIX}/connectors/groq",
        json={"api_key": "rotated-key-12345678", "title": "G"},
    )

    assert response.status_code == 200
    assert (response.json()["title"], response.json()["secret_last4"]) == ("G", "5678")
    assert world.secrets.store["groq"]["api_key"] == "rotated-key-12345678"


async def test_a_routed_connector_cannot_be_deleted_until_the_route_goes(
    client: AsyncClient, world: World
) -> None:
    await client.post(f"{PREFIX}/connectors", json=GROQ)
    put = await client.put(
        f"{PREFIX}/pipelines/studio", json={"connector_id": "groq", "model": "llama-4"}
    )
    assert put.status_code == 200

    blocked = await client.delete(f"{PREFIX}/connectors/groq")
    assert (blocked.status_code, blocked.json()["type"]) == (409, "connector_in_use")
    assert blocked.json()["params"] == {"pipelines": "studio"}
    assert "groq" in world.secrets.store

    assert (await client.delete(f"{PREFIX}/pipelines/studio")).status_code == 204
    assert (await client.delete(f"{PREFIX}/connectors/groq")).status_code == 204
    assert world.secrets.store == {}


async def test_the_connector_test_is_ok_in_fake_mode_and_404_for_unknown(
    client: AsyncClient,
) -> None:
    ok = await client.post(f"{PREFIX}/connectors/openrouter/test")
    missing = await client.post(f"{PREFIX}/connectors/nope/test")

    assert ok.status_code == 200
    assert ok.json() == {"ok": True, "latency_ms": 0, "error": None}
    assert missing.status_code == 404


async def test_the_pipelines_list_shows_every_pipeline_with_tasks_and_defaults(
    client: AsyncClient,
) -> None:
    response = await client.get(f"{PREFIX}/pipelines")

    assert response.status_code == 200
    items = {i["pipeline"]: i for i in response.json()["items"]}
    assert len(items) == 10
    studio = items["studio"]
    assert "studio_quiz" in studio["tasks"]
    assert studio["route"] == {
        "connector_id": None,
        "model": None,
        "reasoning_effort": None,
        "updated_at": None,
    }
    assert studio["effective"]["source"] == "env"
    assert studio["env_default"]["connector_id"] == "openrouter"
    assert items["web_search"]["env_default"]["connector_id"] == "exa"


async def test_a_put_stores_the_route_and_reports_it_as_effective(
    client: AsyncClient, world: World
) -> None:
    response = await client.put(
        f"{PREFIX}/pipelines/studio",
        json={
            "connector_id": "openrouter",
            "model": "google/gemini-3.8-flash",
            "reasoning_effort": "low",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["route"]["model"] == "google/gemini-3.8-flash"
    assert body["route"]["updated_at"] is not None
    assert body["effective"] == {
        "connector_id": "openrouter",
        "model": "google/gemini-3.8-flash",
        "reasoning_effort": "low",
        "source": "runtime",
    }
    async with world.sessionmaker() as session:
        row = await session.scalar(
            select(PipelineRouteRow).where(PipelineRouteRow.pipeline == "studio")
        )
    assert row is not None and row.model == "google/gemini-3.8-flash"
    again = await client.put(f"{PREFIX}/pipelines/studio", json={"model": "m2"})
    assert again.json()["route"]["model"] == "m2"
    listed = {
        i["pipeline"]: i
        for i in (await client.get(f"{PREFIX}/pipelines")).json()["items"]
    }
    assert listed["studio"]["effective"]["model"] == "m2"
    assert listed["chat"]["effective"]["source"] == "env"


async def test_put_refuses_unknown_pipelines_connectors_kinds_and_values(
    client: AsyncClient,
) -> None:
    unknown = await client.put(f"{PREFIX}/pipelines/nope", json={"model": "m"})
    ghost = await client.put(f"{PREFIX}/pipelines/chat", json={"connector_id": "ghost"})
    mismatch = await client.put(
        f"{PREFIX}/pipelines/chat", json={"connector_id": "exa"}
    )
    search = await client.put(
        f"{PREFIX}/pipelines/web_search", json={"connector_id": "openrouter"}
    )
    effort = await client.put(
        f"{PREFIX}/pipelines/chat", json={"reasoning_effort": "max"}
    )

    assert (unknown.status_code, unknown.json()["type"]) == (404, "pipeline_not_found")
    assert (ghost.status_code, ghost.json()["type"]) == (404, "connector_not_found")
    assert (mismatch.status_code, mismatch.json()["type"]) == (
        422,
        "connector_kind_mismatch",
    )
    assert search.status_code == 422
    assert effort.status_code == 422
    assert (await client.delete(f"{PREFIX}/pipelines/nope")).status_code == 404


async def test_students_cannot_reach_connectors_or_pipelines(
    http_client: HttpClientFactory,
    settings: Settings,
    clock: FixedClock,
    world: World,
) -> None:
    student = Actor(user_id=new_id(), roles=frozenset({Role.STUDENT}))
    client = await _client(http_client, settings, clock, world, student)

    assert (await client.get(f"{PREFIX}/connectors")).status_code == 403
    assert (await client.post(f"{PREFIX}/connectors", json=GROQ)).status_code == 403
    assert (await client.get(f"{PREFIX}/pipelines")).status_code == 403
    assert (
        await client.put(f"{PREFIX}/pipelines/chat", json={"model": "m"})
    ).status_code == 403
