"""Private-content tasks leave no input, output or error text in traces."""

from app.modules.ai.infrastructure import recording_gateways
from app.modules.ai.infrastructure.langfuse_tracer import PRIVATE_ERROR_CODE
from tests.ai.unit.test_langfuse_tracer import _Backend, _call, _gateway

import pytest


async def test_private_task_sends_no_content(monkeypatch: pytest.MonkeyPatch) -> None:
    """A private task opens the span without input and closes it without output."""
    monkeypatch.setattr(recording_gateways, "is_private_task", lambda task: True)
    backend = _Backend()

    await _call(_gateway(backend, capture=True))

    span = backend.spans[0]
    assert span.started["input"] is None
    assert span.ended is not None
    assert span.ended["output"] is None


async def test_public_task_keeps_content_when_capture_is_on() -> None:
    """The default (non-private) behaviour is unchanged."""
    backend = _Backend()

    await _call(_gateway(backend, capture=True))

    assert backend.spans[0].started["input"] is not None


def test_unknown_task_is_not_private() -> None:
    """A task name outside the registry is treated as non-private."""
    assert recording_gateways.is_private_task("no_such_task") is False


def test_error_code_is_fixed() -> None:
    """The replacement error carries no model or user text."""
    assert PRIVATE_ERROR_CODE == "private_task_error"
