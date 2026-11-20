"""Connector administration, the Vault key store, URL rules and the compat gateway."""

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

from app.modules.ai.application.connectors import ConnectorAdmin, PipelineAdmin
from app.modules.ai.application.routing import RouteService
from app.modules.ai.domain.connectors import (
    Connector,
    ConnectorKind,
    Pipeline,
    PipelineRoute,
    kind_fits,
    valid_base_url,
    valid_slug,
)
from app.modules.ai.domain.errors import (
    ConnectorExistsError,
    ConnectorInUseError,
    ConnectorInvalidError,
    ConnectorKindMismatchError,
    ConnectorNotFoundError,
    ConnectorSecretUnavailableError,
    PipelineNotFoundError,
)
from app.modules.ai.infrastructure.connector_vault import (
    DisabledConnectorSecrets,
    VaultConnectorSecrets,
)
from app.modules.ai.infrastructure.openai_compatible_gateway import (
    OpenAiCompatibleGateway,
)
from app.settings import AiConnectorVaultSettings, Settings
from app.shared.actor import Actor, Role
from app.shared.ids import new_id
from tests.fakes.ai_connectors import (
    ConnectorWorld,
    FakeConnectorUow,
    FakeLoader,
    FakeRuntime,
    FakeSecrets,
)
from tests.fakes.clock import FixedClock

import httpx
import pytest
from hvac.exceptions import InvalidPath

ACTOR = Actor(user_id=new_id(), roles=frozenset({Role.ADMIN}))
KEY = "sk-secret-key-0123456789"


class Stack(SimpleNamespace):
    """The services over one fake world."""

    world: ConnectorWorld
    secrets: FakeSecrets
    runtime: FakeRuntime
    routing: RouteService
    connectors: ConnectorAdmin
    pipelines: PipelineAdmin


def _stack(*, vault: bool = True, plain_local: bool = False) -> Stack:
    world = ConnectorWorld()
    secrets = FakeSecrets(available=vault)
    runtime = FakeRuntime()
    routing = RouteService(Settings(env="test"), FakeLoader(world), runtime)

    def make_uow() -> FakeConnectorUow:
        return FakeConnectorUow(world)

    return Stack(
        world=world,
        secrets=secrets,
        runtime=runtime,
        routing=routing,
        connectors=ConnectorAdmin(
            make_uow, secrets, runtime, routing, allow_plain_local_urls=plain_local
        ),
        pipelines=PipelineAdmin(make_uow, runtime, routing, FixedClock()),
    )


async def _add_groq(stack: Stack) -> Connector:
    return await stack.connectors.create(
        ACTOR,
        id="groq",
        kind=ConnectorKind.OPENAI_COMPATIBLE,
        title="Groq",
        base_url="https://api.groq.com/openai/v1",
        api_key=KEY,
        headers={"X-Team": "iht"},
    )


# - - - domain rules - - -


@pytest.mark.parametrize("slug", ["groq", "my-llm_2", "ab"])
def test_good_slugs(slug: str) -> None:
    assert valid_slug(slug)


@pytest.mark.parametrize("slug", ["a", "1abc", "Groq", "has space", "x" * 49, ""])
def test_bad_slugs(slug: str) -> None:
    assert not valid_slug(slug)


@pytest.mark.parametrize(
    ("url", "plain_local", "ok"),
    [
        ("https://api.groq.com/openai/v1", False, True),
        ("http://api.groq.com/v1", True, False),
        ("http://localhost:8000/v1", False, False),
        ("http://localhost:8000/v1", True, True),
        ("ftp://x.example", True, False),
        ("https://user:pw@x.example", False, False),
        ("not a url", False, False),
    ],
)
def test_base_url_rules(url: str, plain_local: bool, ok: bool) -> None:
    assert valid_base_url(url, allow_plain_local=plain_local) is ok


def test_search_connectors_fit_only_the_search_pipeline() -> None:
    assert kind_fits(ConnectorKind.EXA, Pipeline.WEB_SEARCH)
    assert not kind_fits(ConnectorKind.EXA, Pipeline.CHAT)
    assert kind_fits(ConnectorKind.OPENAI_COMPATIBLE, Pipeline.STUDIO)
    assert not kind_fits(ConnectorKind.OPENROUTER, Pipeline.WEB_SEARCH)


# - - - connectors - - -


async def test_the_list_has_the_environment_connectors_first() -> None:
    stack = _stack()

    rows = await stack.connectors.list(ACTOR)

    assert [r.id for r in rows] == ["openrouter", "anthropic", "exa"]
    assert all(r.builtin and r.source == "env" for r in rows)


async def test_adding_a_connector_writes_vault_first_and_never_stores_the_key() -> None:
    stack = _stack()

    row = await _add_groq(stack)

    assert stack.secrets.store["groq"] == {
        "api_key": KEY,
        "headers": {"X-Team": "iht"},
    }
    assert (row.has_secret, row.secret_last4, row.source) == (True, "6789", "db")
    assert KEY not in repr(stack.world.connectors["groq"])
    assert [d.type for d in stack.world.audit] == ["admin.ai_connector_added"]
    assert KEY not in repr(stack.world.audit)
    assert [r.id for r in await stack.connectors.list(ACTOR)][-1] == "groq"


async def test_a_short_key_shows_no_last_characters() -> None:
    stack = _stack()

    row = await stack.connectors.create(
        ACTOR,
        id="local",
        kind=ConnectorKind.OPENAI_COMPATIBLE,
        title="Local",
        base_url="https://llm.example",
        api_key="abcd",
        headers=None,
    )

    assert row.has_secret and row.secret_last4 is None


async def test_a_duplicate_id_or_a_built_in_id_is_a_conflict() -> None:
    stack = _stack()
    await _add_groq(stack)

    for taken in ("groq", "openrouter"):
        with pytest.raises(ConnectorExistsError):
            await stack.connectors.create(
                ACTOR,
                id=taken,
                kind=ConnectorKind.OPENAI_COMPATIBLE,
                title="x",
                base_url="https://x.example",
                api_key=None,
                headers=None,
            )


@pytest.mark.parametrize(
    ("kind", "slug", "url", "field"),
    [
        (ConnectorKind.OPENAI_COMPATIBLE, "BAD", "https://x.example", "id"),
        (ConnectorKind.OPENAI_COMPATIBLE, "ok1", None, "base_url"),
        (ConnectorKind.OPENAI_COMPATIBLE, "ok1", "http://x.example", "base_url"),
        (ConnectorKind.OPENAI_COMPATIBLE, "ok1", "http://localhost:1", "base_url"),
    ],
)
async def test_invalid_fields_are_refused(
    kind: ConnectorKind, slug: str, url: str | None, field: str
) -> None:
    stack = _stack(plain_local=False)

    with pytest.raises(ConnectorInvalidError) as error:
        await stack.connectors.create(
            ACTOR,
            id=slug,
            kind=kind,
            title="t",
            base_url=url,
            api_key=None,
            headers=None,
        )

    assert error.value.params == {"field": field}
    assert stack.world.connectors == {}


async def test_plain_http_localhost_is_allowed_in_development() -> None:
    stack = _stack(plain_local=True)

    row = await stack.connectors.create(
        ACTOR,
        id="local",
        kind=ConnectorKind.OPENAI_COMPATIBLE,
        title="Local",
        base_url="http://localhost:8000/v1/",
        api_key=None,
        headers=None,
    )

    assert row.base_url == "http://localhost:8000/v1"
    assert not row.has_secret


async def test_a_key_cannot_be_saved_while_vault_is_off() -> None:
    stack = _stack()
    stack.connectors.secrets = DisabledConnectorSecrets()

    with pytest.raises(ConnectorSecretUnavailableError):
        await _add_groq(stack)

    assert stack.world.connectors == {}
    assert stack.world.audit == []


async def test_a_dead_vault_leaves_no_row() -> None:
    stack = _stack(vault=False)

    with pytest.raises(ConnectorSecretUnavailableError):
        await _add_groq(stack)

    assert stack.world.connectors == {}


async def test_a_failing_insert_removes_the_written_secret() -> None:
    stack = _stack()
    original = FakeConnectorUow.commit

    async def boom(self: FakeConnectorUow) -> None:
        raise RuntimeError("commit failed")

    FakeConnectorUow.commit = boom  # type: ignore[method-assign]
    try:
        with pytest.raises(RuntimeError):
            await _add_groq(stack)
    finally:
        FakeConnectorUow.commit = original  # type: ignore[method-assign]

    assert stack.secrets.store == {}


async def test_patching_a_connector_rotates_the_key_and_keeps_the_rest() -> None:
    stack = _stack()
    await _add_groq(stack)

    row = await stack.connectors.update(
        ACTOR, "groq", title="Groq Cloud", enabled=False, api_key="new-key-abcdefgh"
    )

    assert (row.title, row.enabled, row.secret_last4) == ("Groq Cloud", False, "efgh")
    assert row.base_url == "https://api.groq.com/openai/v1"
    assert stack.secrets.store["groq"]["api_key"] == "new-key-abcdefgh"
    assert stack.world.audit[-1].type == "admin.ai_connector_updated"
    assert "api_key" not in repr(stack.world.audit[-1].metadata)


async def test_patching_a_built_in_creates_an_override_row() -> None:
    stack = _stack()

    row = await stack.connectors.update(ACTOR, "openrouter", enabled=False)

    assert (row.id, row.enabled, row.source, row.builtin) == (
        "openrouter",
        False,
        "db",
        True,
    )
    listed = {c.id: c for c in await stack.connectors.list(ACTOR)}
    assert listed["openrouter"].source == "db" and not listed["openrouter"].enabled


async def test_patching_an_unknown_connector_is_not_found() -> None:
    with pytest.raises(ConnectorNotFoundError):
        await _stack().connectors.update(ACTOR, "nope", title="x")


async def test_deleting_removes_the_row_and_the_secret() -> None:
    stack = _stack()
    await _add_groq(stack)

    await stack.connectors.delete(ACTOR, "groq")

    assert stack.world.connectors == {} and stack.secrets.store == {}
    assert stack.world.audit[-1].type == "admin.ai_connector_removed"


async def test_deleting_a_built_in_override_returns_it_to_the_environment() -> None:
    stack = _stack()
    await stack.connectors.update(ACTOR, "openrouter", enabled=False)

    await stack.connectors.delete(ACTOR, "openrouter")
    await stack.connectors.delete(ACTOR, "openrouter")  # nothing left: no error

    listed = {c.id: c for c in await stack.connectors.list(ACTOR)}
    assert listed["openrouter"].source == "env" and listed["openrouter"].enabled


async def test_deleting_an_unknown_connector_is_not_found() -> None:
    with pytest.raises(ConnectorNotFoundError):
        await _stack().connectors.delete(ACTOR, "nope")


async def test_a_routed_connector_cannot_be_deleted() -> None:
    stack = _stack()
    await _add_groq(stack)
    await stack.pipelines.put(
        ACTOR, "studio", connector_id="groq", model=None, reasoning_effort=None
    )
    await stack.pipelines.put(
        ACTOR, "chat", connector_id="groq", model=None, reasoning_effort=None
    )

    with pytest.raises(ConnectorInUseError) as error:
        await stack.connectors.delete(ACTOR, "groq")

    assert error.value.params == {"pipelines": "chat, studio"}
    assert "groq" in stack.world.connectors and "groq" in stack.secrets.store


async def test_the_test_call_reports_the_probe_and_unknown_ids() -> None:
    stack = _stack()

    ok = await stack.connectors.test(ACTOR, "openrouter")

    assert (ok.ok, ok.latency_ms, ok.error) == (True, 12, None)
    with pytest.raises(ConnectorNotFoundError):
        await stack.connectors.test(ACTOR, "nope")


# - - - pipelines - - -


async def test_the_pipeline_list_has_every_pipeline_with_its_tasks() -> None:
    stack = _stack()

    views = await stack.pipelines.list(ACTOR)

    assert [v.pipeline for v in views] == list(Pipeline)
    studio = next(v for v in views if v.pipeline is Pipeline.STUDIO)
    assert "studio_quiz" in studio.tasks and studio.route is None
    assert studio.effective.source == "env"
    assert studio.env_default.connector_id == "openrouter"


async def test_putting_a_route_shows_it_as_effective_and_audits_it() -> None:
    stack = _stack()

    view = await stack.pipelines.put(
        ACTOR,
        "studio",
        connector_id="openrouter",
        model="google/gemini-3.8-flash",
        reasoning_effort="low",
    )

    assert view.route is not None and view.route.model == "google/gemini-3.8-flash"
    assert (view.effective.model, view.effective.source) == (
        "google/gemini-3.8-flash",
        "runtime",
    )
    assert view.env_default.model == "anthropic/claude-haiku-5.5"
    assert stack.world.audit[-1].type == "admin.ai_pipeline_routed"
    metadata = stack.world.audit[-1].metadata
    assert metadata is not None and metadata["pipeline"] == "studio"


async def test_a_put_shows_in_the_next_route_at_once() -> None:
    stack = _stack()
    from app.shared.ai_tasks import AiTask

    await stack.routing.route(AiTask.STUDIO_QUIZ)  # fills the cache
    await stack.pipelines.put(
        ACTOR, "studio", connector_id=None, model="m2", reasoning_effort=None
    )

    assert (await stack.routing.route(AiTask.STUDIO_QUIZ)).model == "m2"


async def test_an_empty_put_removes_the_route() -> None:
    stack = _stack()
    await stack.pipelines.put(
        ACTOR, "chat", connector_id=None, model="m", reasoning_effort=None
    )

    view = await stack.pipelines.put(
        ACTOR, "chat", connector_id=None, model=None, reasoning_effort=None
    )

    assert view.route is None and stack.world.routes == {}


async def test_put_rejects_unknown_pipelines_connectors_and_bad_values() -> None:
    stack = _stack()
    with pytest.raises(PipelineNotFoundError):
        await stack.pipelines.put(
            ACTOR, "nope", connector_id=None, model="m", reasoning_effort=None
        )
    with pytest.raises(ConnectorNotFoundError):
        await stack.pipelines.put(
            ACTOR, "chat", connector_id="ghost", model=None, reasoning_effort=None
        )
    with pytest.raises(ConnectorKindMismatchError):
        await stack.pipelines.put(
            ACTOR, "chat", connector_id="exa", model=None, reasoning_effort=None
        )
    with pytest.raises(ConnectorKindMismatchError):
        await stack.pipelines.put(
            ACTOR,
            "web_search",
            connector_id="openrouter",
            model=None,
            reasoning_effort=None,
        )
    with pytest.raises(ConnectorInvalidError):
        await stack.pipelines.put(
            ACTOR, "chat", connector_id=None, model=None, reasoning_effort="max"
        )
    assert stack.world.routes == {}


async def test_deleting_a_route_returns_to_the_environment() -> None:
    stack = _stack()
    await stack.pipelines.put(
        ACTOR, "chat", connector_id=None, model="m", reasoning_effort=None
    )

    await stack.pipelines.delete(ACTOR, "chat")

    assert stack.world.routes == {}
    with pytest.raises(PipelineNotFoundError):
        await stack.pipelines.delete(ACTOR, "nope")


async def test_the_stored_route_survives_in_the_domain_type() -> None:
    route = PipelineRoute(Pipeline.CHAT, None, "m", None)
    assert route.updated_at is None and route.updated_by is None


# - - - Vault key store - - -


class _FakeKv:
    """hvac's KV v2 in memory."""

    def __init__(self) -> None:
        self.data: dict[tuple[str, str], dict[str, Any]] = {}

    def create_or_update_secret(
        self, *, path: str, secret: dict[str, Any], mount_point: str
    ) -> None:
        self.data[(mount_point, path)] = secret

    def read_secret_version(
        self, *, path: str, mount_point: str, raise_on_deleted_version: bool
    ) -> dict[str, Any]:
        if (mount_point, path) not in self.data:
            raise InvalidPath()
        return {"data": {"data": self.data[(mount_point, path)]}}

    def delete_metadata_and_all_versions(self, *, path: str, mount_point: str) -> None:
        if (mount_point, path) not in self.data:
            raise InvalidPath()
        del self.data[(mount_point, path)]


def _vault(monkeypatch: pytest.MonkeyPatch) -> tuple[VaultConnectorSecrets, _FakeKv]:
    kv = _FakeKv()
    client = MagicMock()
    client.secrets.kv.v2 = kv
    monkeypatch.setattr("hvac.Client", lambda **_: client)
    return VaultConnectorSecrets(AiConnectorVaultSettings(enabled=True)), kv


async def test_the_vault_store_round_trips_under_the_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, kv = _vault(monkeypatch)

    assert await store.get("groq") is None
    await store.put("groq", {"api_key": KEY, "headers": {"X": "1"}})

    assert await store.get("groq") == {"api_key": KEY, "headers": {"X": "1"}}
    assert list(kv.data) == [("secret", "ai/connectors/groq")]
    await store.delete("groq")
    await store.delete("groq")  # a missing secret is fine
    assert await store.get("groq") is None


async def test_a_vault_failure_becomes_the_unavailable_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, kv = _vault(monkeypatch)

    def broken(**_: Any) -> None:
        raise OSError("connection refused")

    kv.create_or_update_secret = broken  # type: ignore[method-assign]

    with pytest.raises(ConnectorSecretUnavailableError) as error:
        await store.put("groq", {"api_key": KEY})

    assert KEY not in str(error.value)


async def test_the_disabled_store_refuses_to_save_and_has_nothing() -> None:
    store = DisabledConnectorSecrets()

    assert await store.get("x") is None
    await store.delete("x")
    with pytest.raises(ConnectorSecretUnavailableError):
        await store.put("x", {"api_key": "k"})


def test_the_vault_defaults_are_off_with_the_contract_prefix() -> None:
    settings = Settings(env="test")

    assert settings.ai_connector_vault.enabled is False
    assert settings.ai_connector_vault.kv_prefix == "ai/connectors"


# - - - OpenAI-compatible gateway - - -


def _capture() -> tuple[httpx.AsyncClient, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "hi"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 2},
            },
        )

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://llm.example/v1"
    )
    return client, seen


async def test_the_compat_gateway_sends_only_standard_fields_and_its_headers() -> None:
    from app.shared.contracts.ai import LlmTuning

    client, seen = _capture()
    gateway = OpenAiCompatibleGateway(
        api_key=KEY,
        base_url="https://llm.example/v1",
        timeout_seconds=5,
        headers={"X-Team": "iht"},
        client=client,
    )

    result = await gateway.complete(
        model="llama-4",
        system="be brief",
        messages=[{"role": "user", "content": "hello"}],
        tools=[],
        max_tokens=50,
        provider={"data_collection": "deny"},
        tuning=LlmTuning(
            temperature=0.1, reasoning_effort="high", fallbacks=("other",)
        ),
    )

    assert result["text"] == "hi"
    request = seen[0]
    assert str(request.url) == "https://llm.example/v1/chat/completions"
    assert request.headers["authorization"] == f"Bearer {KEY}"
    assert request.headers["x-team"] == "iht"
    assert "http-referer" not in request.headers
    body = __import__("json").loads(request.content)
    assert body["model"] == "llama-4" and body["reasoning_effort"] == "high"
    assert not {"provider", "models", "reasoning"} & set(body)
    assert body["messages"][0] == {"role": "system", "content": "be brief"}


async def test_the_compat_gateway_works_without_a_key() -> None:
    client, seen = _capture()
    gateway = OpenAiCompatibleGateway(
        api_key=None,
        base_url="http://localhost:8000/v1",
        timeout_seconds=5,
        client=client,
    )

    await gateway.complete(model="m", system="s", messages=[], tools=[], max_tokens=5)

    assert "authorization" not in seen[0].headers
