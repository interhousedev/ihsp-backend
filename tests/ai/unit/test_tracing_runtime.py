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
from app.shared.ai_tasks import ADMISSION_TASKS
from app.shared.contracts.ai import LlmTuning
from tests.ai.unit.test_langfuse_tracer import _Backend, _Sink
from tests.fakes.ai_connectors import FakeSecrets
from tests.fakes.clock import FixedClock

ADMISSION_TASK = sorted(t.value for t in ADMISSION_TASKS)[0]
PROJECT = TracingConfig(
    host="https://lf.example.com",
    public_key="pk-rt",
    has_secret=True,
    secret_last4="1234",
)


class _Maker:
    """Builds fake-backed tracers and remembers the arguments it got."""

    def __init__(self) -> None:
        self.backends: list[_Backend] = []
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> LangfuseTracer:
        backend = _Backend()
        self.backends.append(backend)
        self.calls.append(kwargs)
        return LangfuseTracer(backend, capture_content=kwargs["capture_content"])


async def _secrets() -> FakeSecrets:
    secrets = FakeSecrets()
    await secrets.put(LANGFUSE_SECRET_ID, {"secret_key": "sk-runtime-1234"})
    return secrets


async def _traced(maker: _Maker, **routes: PipelineRoute) -> TracingRuntime:
    runtime = TracingRuntime(make=maker)
    snapshot = RoutingSnapshot(
        routes={Pipeline(k): v for k, v in routes.items()}, tracing=PROJECT
    )
    await runtime.apply(snapshot, await _secrets())
    return runtime


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


async def test_nothing_is_traced_without_a_stored_project() -> None:
    maker = _Maker()
    runtime = TracingRuntime(make=maker)
    await runtime.apply(RoutingSnapshot(), FakeSecrets())
    await _call(runtime, "student_chat")
    assert maker.calls == []
    assert runtime.tracer_for("student_chat") is None


async def test_admission_is_untraced_by_default() -> None:
    maker = _Maker()
    runtime = await _traced(maker)
    await _call(runtime, ADMISSION_TASK)
    assert maker.backends[0].spans == []
    await _call(runtime, "student_chat")
    assert len(maker.backends[0].spans) == 1
    assert maker.backends[0].spans[0].started["input"] is None


async def test_disabled_pipeline_never_calls_the_tracer() -> None:
    maker = _Maker()
    runtime = await _traced(maker, chat=_route(Pipeline.CHAT, tracing_enabled=False))
    await _call(runtime, "student_chat")
    assert maker.backends[0].spans == []


async def test_capture_override_sends_content() -> None:
    maker = _Maker()
    runtime = await _traced(maker, chat=_route(Pipeline.CHAT, capture_content=True))
    await _call(runtime, "student_chat")
    assert maker.backends[0].spans[0].started["input"] is not None


async def test_stored_project_builds_the_client_and_removal_stops_it() -> None:
    maker = _Maker()
    runtime = await _traced(maker)
    await _call(runtime, "student_chat")
    assert len(maker.backends[0].spans) == 1
    assert maker.calls == [
        {
            "public_key": "pk-rt",
            "secret_key": "sk-runtime-1234",
            "host": "https://lf.example.com",
            "capture_content": False,
        }
    ]
    await runtime.apply(RoutingSnapshot(), FakeSecrets())
    assert runtime.tracer_for("student_chat") is None
