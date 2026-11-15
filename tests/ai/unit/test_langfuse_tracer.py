"""Langfuse tracing: off means no client, no content in spans, errors swallowed."""

from typing import Any
from uuid import uuid4

from app.modules.ai.infrastructure import langfuse_tracer
from app.modules.ai.infrastructure.fake_llm import FakeLlmGateway
from app.modules.ai.infrastructure.langfuse_tracer import (
    LangfuseTracer,
    make_langfuse_tracer,
)
from app.modules.ai.infrastructure.recording_gateways import (
    RecordingLlmGateway,
    UsageRecorder,
)
from app.settings import LangfuseSettings
from app.shared.contracts.ai import LlmGateway, LlmTuning
from app.shared.usage_context import UsageActor, _current, bind_ai_session
from tests.fakes.clock import FixedClock

import pytest


class _Sink:
    async def write(self, event: Any) -> None:
        return None


class _Span:
    def __init__(self, started: dict[str, Any]) -> None:
        self.started = started
        self.ended: dict[str, Any] | None = None

    def end(self, **kwargs: Any) -> None:
        self.ended = kwargs


class _Backend:
    def __init__(self, *, fail: bool = False) -> None:
        self.spans: list[_Span] = []
        self.fail = fail
        self.shut = False

    def start(self, **kwargs: Any) -> _Span:
        if self.fail:
            raise RuntimeError("langfuse down")
        span = _Span(kwargs)
        self.spans.append(span)
        return span

    def flush(self) -> None:
        if self.fail:
            raise RuntimeError("langfuse down")

    def shutdown(self) -> None:
        self.shut = True
        if self.fail:
            raise RuntimeError("langfuse down")


def _gateway(backend: _Backend, *, capture: bool) -> RecordingLlmGateway:
    tracer = LangfuseTracer(backend, salt="s", capture_content=capture)
    recorder = UsageRecorder(_Sink(), FixedClock(), tracer)
    inner: LlmGateway = FakeLlmGateway()
    return RecordingLlmGateway(inner, recorder)


async def _call(gateway: RecordingLlmGateway) -> None:
    await gateway.complete(
        model="m",
        system="SECRET-SYSTEM",
        messages=[{"role": "user", "content": "SECRET-TEXT"}],
        tools=[],
        max_tokens=50,
        tuning=LlmTuning(task="student_chat"),
    )


def test_disabled_creates_no_client(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("client must not be created")

    monkeypatch.setattr("langfuse.Langfuse", boom)
    assert make_langfuse_tracer(LangfuseSettings()) is None
    assert make_langfuse_tracer(LangfuseSettings(public_key="pk")) is None


def test_enabled_creates_client(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    class _Client:
        def __init__(self, **kwargs: Any) -> None:
            seen.update(kwargs)

    monkeypatch.setattr("langfuse.Langfuse", _Client)
    tracer = make_langfuse_tracer(LangfuseSettings(public_key="pk", secret_key="sk"))
    assert tracer is not None and seen["public_key"] == "pk"
    assert seen["host"] == "https://cloud.langfuse.com"


async def test_span_has_no_content_when_capture_off() -> None:
    backend = _Backend()
    user = uuid4()
    token = _current.set(UsageActor(user, "student"))
    bind_ai_session("chat-1")
    try:
        await _call(_gateway(backend, capture=False))
    finally:
        _current.reset(token)
    (span,) = backend.spans
    assert span.started["name"] == "student_chat"
    assert span.started["session_id"] == "chat-1"
    assert span.started["input"] is None
    assert span.started["user_id"] not in (None, str(user))
    assert str(user) not in repr(span.started)
    assert span.ended is not None and span.ended["output"] is None
    assert "SECRET" not in repr(span.started) + repr(span.ended)
    assert set(span.ended["usage"]) >= {"input", "output"}


async def test_span_has_content_when_capture_on() -> None:
    backend = _Backend()
    await _call(_gateway(backend, capture=True))
    (span,) = backend.spans
    assert "SECRET-TEXT" in repr(span.started["input"])
    assert span.ended is not None and span.ended["output"] is not None


async def test_backend_errors_are_swallowed() -> None:
    backend = _Backend(fail=True)
    await _call(_gateway(backend, capture=True))  # no exception
    tracer = LangfuseTracer(backend, salt="s", capture_content=False)
    tracer.flush()
    tracer.close()
    assert backend.shut


async def test_end_errors_are_swallowed() -> None:
    backend = _Backend()
    gateway = _gateway(backend, capture=False)

    def boom(**kwargs: Any) -> None:
        raise RuntimeError("down")

    original = backend.start

    def start(**kwargs: Any) -> _Span:
        span = original(**kwargs)
        span.end = boom  # type: ignore[method-assign]
        return span

    backend.start = start  # type: ignore[method-assign]
    await _call(gateway)


def test_module_exports() -> None:
    assert callable(langfuse_tracer.SdkBackend)
