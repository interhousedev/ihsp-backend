"""Which connector, model and effort a call uses (runtime, task, pipeline, default)."""

from dataclasses import replace
from datetime import UTC, datetime
from typing import cast

from app.modules.ai.application.routing import RouteService, current_route
from app.modules.ai.domain.connectors import Connector, ConnectorKind, PipelineRoute
from app.modules.ai.infrastructure.gateway_factory import RoutedLlmGateway
from app.settings import Settings
from app.settings_ai import AiPipelineSettings, AiSettings, AiTaskSettings
from app.shared.ai_tasks import AiTask, Pipeline
from app.shared.contracts.ai import LlmGateway, LlmTuning
from tests.fakes.ai.llm import ScriptedLlm
from tests.fakes.ai_connectors import ConnectorWorld, FakeLoader, FakeRuntime

import pytest


class Ticks:
    """A monotonic clock the test moves."""

    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def _settings(
    pipelines: dict[Pipeline, AiPipelineSettings] | None = None,
    tasks: dict[AiTask, AiTaskSettings] | None = None,
) -> Settings:
    base = Settings(env="test")
    ai = AiSettings(pipelines=pipelines or {}, tasks=tasks or {})
    return base.model_copy(update={"ai": ai})


def _groq() -> Connector:
    return Connector(
        id="groq",
        kind=ConnectorKind.OPENAI_COMPATIBLE,
        title="Groq",
        base_url="https://api.groq.com/openai/v1",
        enabled=True,
        has_secret=True,
        secret_last4="wxyz",
        builtin=False,
        source="db",
    )


def _route(pipeline: Pipeline, **fields: str | None) -> PipelineRoute:
    return PipelineRoute(
        pipeline=pipeline,
        connector_id=fields.get("connector_id"),
        model=fields.get("model"),
        reasoning_effort=fields.get("reasoning_effort"),
        updated_at=datetime(2026, 11, 20, tzinfo=UTC),
    )


def _service(
    settings: Settings, world: ConnectorWorld, ticks: Ticks
) -> tuple[RouteService, FakeRuntime]:
    runtime = FakeRuntime()
    return (
        RouteService(settings, FakeLoader(world), runtime, monotonic=ticks),
        runtime,
    )


async def test_without_routes_the_environment_decides() -> None:
    ticks = Ticks()
    service, _ = _service(_settings(), ConnectorWorld(), ticks)

    route = await service.route(AiTask.STUDENT_CHAT)

    assert route.source == "env"
    assert route.connector_id == "openrouter"
    assert route.model == "anthropic/claude-haiku-5.5"
    assert route.reasoning_effort == "none"
    assert route.pipeline is Pipeline.CHAT


async def test_web_search_defaults_to_exa() -> None:
    service, _ = _service(_settings(), ConnectorWorld(), Ticks())

    route = await service.route(AiTask.WEB_SEARCH)

    assert route.connector_id == "exa"


async def test_environment_pipeline_beats_default_and_task_beats_pipeline() -> None:
    settings = _settings(
        pipelines={
            Pipeline.STUDIO: AiPipelineSettings(
                model="studio/pipeline-model", reasoning_effort="low"
            )
        },
        tasks={AiTask.STUDIO_QUIZ: AiTaskSettings(model="studio/task-model")},
    )
    service, _ = _service(settings, ConnectorWorld(), Ticks())

    quiz = await service.route(AiTask.STUDIO_QUIZ)
    report = await service.route(AiTask.STUDIO_REPORT)

    assert (quiz.model, quiz.reasoning_effort) == ("studio/task-model", "low")
    assert (report.model, report.reasoning_effort) == ("studio/pipeline-model", "low")


async def test_a_runtime_route_beats_every_environment_value_per_field() -> None:
    settings = _settings(
        tasks={AiTask.STUDIO_QUIZ: AiTaskSettings(model="studio/task-model")}
    )
    world = ConnectorWorld(connectors={"groq": _groq()})
    world.routes[Pipeline.STUDIO] = _route(
        Pipeline.STUDIO, connector_id="groq", model="llama-4", reasoning_effort=None
    )
    service, _ = _service(settings, world, Ticks())

    route = await service.route(AiTask.STUDIO_QUIZ)

    assert (route.connector_id, route.model) == ("groq", "llama-4")
    assert route.reasoning_effort == "none"  # null falls through
    assert route.source == "runtime"
    assert route.runtime_model and not route.runtime_effort


async def test_a_route_to_a_disabled_or_unfit_connector_is_ignored() -> None:
    world = ConnectorWorld(connectors={"groq": _groq()})
    world.routes[Pipeline.CHAT] = _route(Pipeline.CHAT, connector_id="groq")
    world.routes[Pipeline.NOTEBOOKS] = _route(Pipeline.NOTEBOOKS, connector_id="exa")
    world.connectors["groq"] = replace(_groq(), enabled=False)
    service, _ = _service(_settings(), world, Ticks())

    chat = await service.route(AiTask.STUDENT_CHAT)
    notebooks = await service.route(AiTask.NOTEBOOK_CHAT)

    assert chat.connector_id == "openrouter" and chat.source == "env"
    assert notebooks.connector_id == "openrouter" and notebooks.source == "env"


async def test_a_put_applies_to_the_next_call_within_the_ttl_with_a_fake_clock() -> (
    None
):
    ticks = Ticks()
    world = ConnectorWorld()
    service, _ = _service(_settings(), world, ticks)
    before = await service.route(AiTask.STUDIO_QUIZ)

    world.routes[Pipeline.STUDIO] = _route(
        Pipeline.STUDIO, model="google/gemini-3.8-flash"
    )
    ticks.now += 29
    still = await service.route(AiTask.STUDIO_QUIZ)
    ticks.now += 2
    after = await service.route(AiTask.STUDIO_QUIZ)

    assert before.model == still.model == "anthropic/claude-haiku-5.5"
    assert after.model == "google/gemini-3.8-flash"


async def test_invalidate_applies_a_local_change_at_once() -> None:
    ticks = Ticks()
    world = ConnectorWorld()
    service, _ = _service(_settings(), world, ticks)
    await service.route(AiTask.STUDIO_QUIZ)

    world.routes[Pipeline.STUDIO] = _route(Pipeline.STUDIO, model="m2")
    service.invalidate()

    assert (await service.route(AiTask.STUDIO_QUIZ)).model == "m2"
    assert world.loads == 2


async def test_a_failing_read_keeps_the_environment_values() -> None:
    class Broken:
        async def load(self):  # type: ignore[no-untyped-def]
            raise RuntimeError("db down")

    service = RouteService(_settings(), Broken(), FakeRuntime(), monotonic=Ticks())

    assert (await service.route(AiTask.STUDENT_CHAT)).source == "env"


async def test_clients_are_built_once_and_rebuilt_when_the_row_changes() -> None:
    world = ConnectorWorld(connectors={"groq": _groq()})
    service, runtime = _service(_settings(), world, Ticks())

    first = await service.client_for("groq")
    again = await service.client_for("groq")
    service.forget_clients("groq")
    third = await service.client_for("groq")

    assert first is again
    assert third is first  # the fake hands out one object per id
    assert runtime.built == ["groq", "groq"]


async def test_the_routed_gateway_uses_the_runtime_model_effort_and_connector() -> None:
    world = ConnectorWorld(connectors={"groq": _groq()})
    world.routes[Pipeline.STUDIO] = _route(
        Pipeline.STUDIO, connector_id="groq", model="llama-4", reasoning_effort="high"
    )
    service, runtime = _service(_settings(), world, Ticks())
    groq, base = ScriptedLlm(), ScriptedLlm()
    groq.push({"text": "from groq", "tool_calls": [], "usage": {}})
    runtime.clients["groq"] = groq
    gateway = RoutedLlmGateway(cast(LlmGateway, base), service)

    result = await gateway.complete(
        model="anthropic/claude-haiku-5.5",
        system="s",
        messages=[],
        tools=[],
        max_tokens=10,
        tuning=LlmTuning(task="studio_quiz", reasoning_effort="none"),
    )

    assert result["text"] == "from groq"
    assert groq.requests[0]["model"] == "llama-4"
    assert groq.requests[0]["tuning"].reasoning_effort == "high"
    assert base.requests == []
    route = current_route.get()
    assert route is not None and route.connector_id == "groq"


async def test_the_routed_gateway_keeps_the_callers_model_without_a_runtime_route() -> (
    None
):
    service, runtime = _service(_settings(), ConnectorWorld(), Ticks())
    base = ScriptedLlm()
    base.push({"text": "ok", "tool_calls": [], "usage": {}})
    runtime.clients["openrouter"] = base
    gateway = RoutedLlmGateway(cast(LlmGateway, base), service)

    await gateway.complete(
        model="x/custom",
        system="s",
        messages=[],
        tools=[],
        max_tokens=10,
        tuning=LlmTuning(task="student_chat"),
    )

    assert base.requests[0]["model"] == "x/custom"


async def test_a_call_without_a_known_task_goes_to_the_environment_gateway() -> None:
    service, _ = _service(_settings(), ConnectorWorld(), Ticks())
    base = ScriptedLlm()
    base.push({"text": "ok", "tool_calls": [], "usage": {}})
    gateway = RoutedLlmGateway(cast(LlmGateway, base), service)

    await gateway.complete(
        model="m", system="s", messages=[], tools=[], max_tokens=5, tuning=None
    )

    assert len(base.requests) == 1


@pytest.mark.parametrize("task", list(AiTask))
async def test_every_task_resolves_to_a_route(task: AiTask) -> None:
    service, _ = _service(_settings(), ConnectorWorld(), Ticks())

    route = await service.route(task)

    assert route.connector_id in {"openrouter", "exa"}
    assert route.model
