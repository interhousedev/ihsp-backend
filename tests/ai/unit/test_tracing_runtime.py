"""Per-pipeline tracing: an untraced pipeline never reaches the tracer."""

from typing import Any

from app.modules.ai.domain.connectors import (
    LANGFUSE_SECRET_ID,
    Pipeline,
    PipelineRoute,
    TracingConfig,
)
from app.modules.ai.infrastructure.fake_llm import FakeLlmGateway
from app.modules.ai.infrastructure.langfuse_tracer import LangfuseTracer
from app.modules.ai.infrastructure.recording_gateways import (
    RecordingLlmGateway,
    UsageRecorder,
)
from app.modules.ai.infrastructure.tracing_runtime import TracingRuntime
from app.modules.ai.ports.connectors import RoutingSnapshot
from app.settings import LangfuseSettings
from app.shared.ai_tasks import ADMISSION_TASKS
from app.shared.contracts.ai import LlmTuning
from tests.ai.unit.test_langfuse_tracer import _Backend, _Sink
from tests.fakes.ai_connectors import FakeSecrets
from tests.fakes.clock import FixedClock

from pydantic import SecretStr

ADMISSION_TASK = sorted(t.value for t in ADMISSION_TASKS)[0]
ENV = LangfuseSettings(public_key="pk", secret_key=SecretStr("sk-env"))


class _Maker:
    """Builds fake-backed tracers and remembers the settings it got."""

    def __init__(self) -> None:
        self.backends: list[_Backend] = []
        self.settings: list[LangfuseSettings] = []

    def __call__(self, settings: LangfuseSettings) -> LangfuseTracer:
        backend = _Backend()
        self.backends.append(backend)
        self.settings.append(settings)
        return LangfuseTracer(
            backend, salt="s", capture_content=settings.capture_content
        )


async def _call(runtime: TracingRuntime, task: str) -> None:
    gateway = RecordingLlmGateway(
        FakeLlmGateway(), UsageRecorder(_Sink(), FixedClock(), runtime)
    )
    await gateway.complete(
        model="m",
        system="SYSTEM",
        messages=[{"role": "user", "content": "TEXT"}],
        tools=[],
        max_tokens=50,
        tuning=LlmTuning(task=task),
    )


def _route(pipeline: Pipeline, **kwargs: Any) -> PipelineRoute:
    return PipelineRoute(pipeline, None, None, None, **kwargs)


async def test_admission_is_untraced_by_default() -> None:
    maker = _Maker()
    runtime = TracingRuntime(ENV, make=maker)
    await _call(runtime, ADMISSION_TASK)
    assert maker.backends[0].spans == []
    await _call(runtime, "student_chat")
    assert len(maker.backends[0].spans) == 1


async def test_disabled_pipeline_never_calls_the_tracer() -> None:
    maker = _Maker()
    runtime = TracingRuntime(ENV, make=maker)
    snapshot = RoutingSnapshot(
        routes={Pipeline.CHAT: _route(Pipeline.CHAT, tracing_enabled=False)}
    )
    await runtime.apply(snapshot, FakeSecrets())
    await _call(runtime, "student_chat")
    assert maker.backends[0].spans == []


async def test_capture_override_sends_content() -> None:
    maker = _Maker()
    runtime = TracingRuntime(ENV, make=maker)
    snapshot = RoutingSnapshot(
        routes={Pipeline.CHAT: _route(Pipeline.CHAT, capture_content=True)}
    )
    await runtime.apply(snapshot, FakeSecrets())
    await _call(runtime, "student_chat")
    assert maker.backends[0].spans[0].started["input"] is not None


async def test_runtime_project_replaces_the_environment() -> None:
    maker = _Maker()
    runtime = TracingRuntime(ENV, make=maker)
    secrets = FakeSecrets()
    await secrets.put(LANGFUSE_SECRET_ID, {"secret_key": "sk-runtime-1234"})
    config = TracingConfig(
        host="https://lf.example.com",
        public_key="pk-rt",
        has_secret=True,
        secret_last4="1234",
    )
    await runtime.apply(RoutingSnapshot(tracing=config), secrets)
    await _call(runtime, "student_chat")
    assert maker.backends[0].spans == []
    assert len(maker.backends[1].spans) == 1
    assert maker.settings[1].public_key == "pk-rt"
