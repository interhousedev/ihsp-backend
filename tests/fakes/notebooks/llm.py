"""A scripted LlmGateway for the notebooks tests.

Queue what the next calls should return (or raise); when nothing is queued for a
call the deterministic ``FakeLlmGateway`` answers, so a test can script only the
interesting call and let the others behave as in development.
"""

import json
from collections import deque
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from app.modules.ai.infrastructure.fake_llm import FakeLlmGateway

DEFAULT_USAGE = {"input": 100, "output": 20, "cached": 0, "cost_micro": None}
ANY = "any"


@dataclass(slots=True)
class Scripted:
    """One queued answer: ``payload`` is the data, the text, the chunks or an error."""

    kind: str
    payload: Any
    usage: dict[str, Any] | None = None


class ScriptedLlm:
    """Implements ``LlmGateway`` (``complete``, ``complete_json``, ``stream``).

    Answers are taken in order. A call of one kind (``json``, ``text`` or
    ``stream``) takes the oldest queued answer of its kind or the oldest queued
    error (``queue_error``), whichever was queued first. Errors raise at the call;
    in a stream they may also stand among the chunks and raise when reached.

    Attributes:
        json_requests: Keyword arguments of every ``complete_json`` call.
        text_requests: Keyword arguments of every ``complete`` call.
        stream_requests: Keyword arguments of every ``stream`` call.
        calls: Number of calls of any kind.
        fallback: The fake used when nothing is queued for a call.
    """

    def __init__(self, fallback: FakeLlmGateway | None = None) -> None:
        """Start with nothing queued."""
        self.fallback = fallback or FakeLlmGateway()
        self._queue: deque[Scripted] = deque()
        self.json_requests: list[dict[str, Any]] = []
        self.text_requests: list[dict[str, Any]] = []
        self.stream_requests: list[dict[str, Any]] = []
        self.calls = 0

    # - - - Script - - -

    def queue_json(
        self,
        data_or_exception: dict[str, Any] | Exception,
        usage: dict[str, Any] | None = None,
    ) -> None:
        """Queue the answer of the next ``complete_json`` (a dict, or an error)."""
        self._queue.append(Scripted("json", data_or_exception, usage))

    def queue_text(self, text: str, usage: dict[str, Any] | None = None) -> None:
        """Queue the answer of the next ``complete`` (plain text, no tool calls)."""
        self._queue.append(Scripted("text", text, usage))

    def queue_stream(
        self, chunks: list[str | Exception], usage: dict[str, Any] | None = None
    ) -> None:
        """Queue the deltas of the next ``stream``; an exception raises when reached."""
        self._queue.append(Scripted("stream", list(chunks), usage))

    def queue_error(self, exc: Exception) -> None:
        """Queue an error for the next call of any kind (in queue order)."""
        self._queue.append(Scripted(ANY, exc))

    @property
    def remaining(self) -> int:
        """How many queued answers were not used yet."""
        return len(self._queue)

    def _take(self, kind: str) -> Scripted | None:
        for index, entry in enumerate(self._queue):
            if entry.kind in (kind, ANY):
                del self._queue[index]
                return entry
        return None

    # - - - LlmGateway - - -

    async def complete(self, **kwargs: Any) -> dict[str, Any]:
        """Return the queued text, raise the queued error, or ask the fallback."""
        self.calls += 1
        self.text_requests.append(kwargs)
        entry = self._take("text")
        if entry is None:
            return await self.fallback.complete(**kwargs)
        _raise_if_error(entry.payload)
        usage = {**DEFAULT_USAGE, **(entry.usage or {})}
        return {"text": entry.payload, "tool_calls": [], "usage": usage}

    async def complete_json(self, **kwargs: Any) -> dict[str, Any]:
        """Return the queued document, raise the queued error, or ask the fallback."""
        self.calls += 1
        self.json_requests.append(kwargs)
        entry = self._take("json")
        if entry is None:
            return await self.fallback.complete_json(**kwargs)
        _raise_if_error(entry.payload)
        usage = {**DEFAULT_USAGE, **(entry.usage or {})}
        return {
            "data": entry.payload,
            "text": json.dumps(entry.payload),
            "usage": usage,
        }

    async def stream(self, **kwargs: Any) -> AsyncIterator[dict[str, Any]]:
        """Yield the queued deltas and usage, or what the fallback streams."""
        self.calls += 1
        self.stream_requests.append(kwargs)
        entry = self._take("stream")
        if entry is None:
            async for item in self.fallback.stream(**kwargs):
                yield item
            return
        _raise_if_error(entry.payload)
        for chunk in entry.payload:
            _raise_if_error(chunk)
            yield {"delta": chunk}
        yield {"usage": {**DEFAULT_USAGE, **(entry.usage or {})}}


def _raise_if_error(item: Any) -> None:
    if isinstance(item, Exception):
        raise item
