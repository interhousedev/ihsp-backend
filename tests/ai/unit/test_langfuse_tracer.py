"""Langfuse tracing: off means no client, no content in spans, errors swallowed."""

from typing import Any
from uuid import uuid4

from app.modules.ai.domain.connectors import LANGFUSE_DEFAULT_HOST
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
from app.shared.contracts.ai import LlmGateway, LlmTuning
from app.shared.usage_context import (
    SURFACE_ADMISSION,
    SURFACE_LMS,
    SURFACE_WEB,
    UsageActor,
    _current,
    bind_ai_session,
)
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


class _OptOut:
    def __init__(self, value: bool) -> None:
        self.value = value

    async def limits_tracing(self, user_id: Any) -> bool:
        return self.value


def _gateway(
    backend: _Backend, *, capture: bool, limit_tracing: bool | None = None
) -> RecordingLlmGateway:
    tracer = LangfuseTracer(backend, capture_content=capture)
    opt_out = None if limit_tracing is None else _OptOut(limit_tracing)
    recorder = UsageRecorder(_Sink(), FixedClock(), tracer, opt_out)
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
    for public_key, secret_key in (("", ""), ("pk", ""), ("", "sk"), ("pk", " ")):
        tracer = make_langfuse_tracer(
            public_key=public_key,
            secret_key=secret_key,
            host=LANGFUSE_DEFAULT_HOST,
            capture_content=False,
        )
        assert tracer is None


def test_enabled_creates_client(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    class _Client:
        def __init__(self, **kwargs: Any) -> None:
            seen.update(kwargs)

    monkeypatch.setattr("langfuse.Langfuse", _Client)
    tracer = make_langfuse_tracer(
        public_key="pk",
        secret_key="sk",
        host="https://lf.example.com",
        capture_content=False,
    )
    assert tracer is not None
    assert seen == {
        "public_key": "pk",
        "secret_key": "sk",
        "host": "https://lf.example.com",
    }


async def test_span_has_no_content_when_capture_off() -> None:
    backend = _Backend()
    user = uuid4()
    token = _current.set(UsageActor(user, "student"))
    bind_ai_session(SURFACE_WEB, "chat-1")
    try:
        await _call(_gateway(backend, capture=False))
    finally:
        _current.reset(token)
    (span,) = backend.spans
    assert span.started["name"] == "student_chat"
    assert span.started["session_id"] == "web:chat-1"
    assert span.started["input"] is None
    assert span.ended is not None and span.ended["output"] is None
    assert "SECRET" not in repr(span.started) + repr(span.ended)
    assert set(span.ended["usage"]) >= {"input", "output"}


async def test_span_carries_user_session_and_surface() -> None:
    """The internal user id, the `<surface>:<id>` session and the surface tag."""
    backend = _Backend()
    user = uuid4()
    token = _current.set(UsageActor(user, "student"))
    bind_ai_session(SURFACE_LMS, "nb-7")
    try:
        await _call(_gateway(backend, capture=True))
    finally:
        _current.reset(token)
    (span,) = backend.spans
    assert span.started["user_id"] == str(user)
    assert span.started["session_id"] == "lms:nb-7"
    assert span.started["tags"] == ["lms"]
    assert span.started["metadata"]["surface"] == "lms"
    assert span.started["metadata"]["masked"] is False


@pytest.mark.parametrize(
    ("surface", "limit", "masked"),
    [
        (SURFACE_WEB, True, False),  # general chat keeps its text
        (SURFACE_LMS, True, True),  # anything else is masked for the user
        (SURFACE_LMS, False, False),
        (SURFACE_ADMISSION, False, True),  # admission is always masked
    ],
)
async def test_masked_span_sends_marker_and_keeps_usage(
    surface: str, limit: bool, masked: bool
) -> None:
    backend = _Backend()
    user = uuid4()
    token = _current.set(UsageActor(user, "student"))
    bind_ai_session(surface, "c")
    try:
        await _call(_gateway(backend, capture=True, limit_tracing=limit))
    finally:
        _current.reset(token)
    (span,) = backend.spans
    assert span.ended is not None
    assert span.started["user_id"] == str(user)
    assert span.started["metadata"]["masked"] is masked
    assert set(span.ended["usage"]) >= {"input", "output"}
    if masked:
        assert span.started["input"] == "[redacted]"
        assert span.ended["output"] == "[redacted]"
        assert "SECRET" not in repr(span.started) + repr(span.ended)
    else:
        assert "SECRET-TEXT" in repr(span.started["input"])


async def test_span_has_content_when_capture_on() -> None:
    backend = _Backend()
    await _call(_gateway(backend, capture=True))
    (span,) = backend.spans
    assert "SECRET-TEXT" in repr(span.started["input"])
    assert span.ended is not None and span.ended["output"] is not None


async def test_backend_errors_are_swallowed() -> None:
    backend = _Backend(fail=True)
    await _call(_gateway(backend, capture=True))  # no exception
    tracer = LangfuseTracer(backend, capture_content=False)
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
