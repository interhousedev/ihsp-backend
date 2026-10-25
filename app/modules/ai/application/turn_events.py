"""Live events of one turn for the streaming variant of the chat endpoints.

The turn runs in a task of its own and puts events on a queue: `step` (a step
started or finished), `status` (the line the pending answer shows), `delta` (a
piece of the text the model is writing), `round_end` (that text was a progress
note before tool calls, not the answer), then `done` (the result) or `error`.
"""

import asyncio
from collections.abc import AsyncIterator, Callable, Coroutine
from dataclasses import dataclass
from typing import Any

from app.modules.ai.application.views import TurnResultView
from app.shared.agent_steps import AgentStep
from app.shared.base_error import BaseError

import structlog

log = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class TurnEvent:
    """One server-sent event; `done` carries the `TurnResultView` as `result`."""

    name: str
    data: dict[str, Any]
    result: TurnResultView | None = None


class TurnEvents:
    """The queue a running turn writes its events to."""

    def __init__(self) -> None:
        """Start with an empty queue."""
        self.queue: asyncio.Queue[TurnEvent] = asyncio.Queue()

    def emit(self, name: str, data: dict[str, Any]) -> None:
        """Queue one event."""
        self.queue.put_nowait(TurnEvent(name, data))

    def status(self, text: str) -> None:
        """Queue the status line of the pending answer."""
        if text.strip():
            self.emit("status", {"text": text.strip()})

    def step(self, item: AgentStep) -> None:
        """Queue a step that started or finished."""
        self.emit("step", item.model_dump(mode="json"))


async def run_streamed(
    events: TurnEvents, turn: Callable[[], Coroutine[Any, Any, TurnResultView]]
) -> AsyncIterator[TurnEvent]:
    """Run `turn` and yield its events, then `done` or `error`.

    An error before the first event (a refusal: limit, unknown chat) is raised, so
    the endpoint can answer with a plain problem response instead of a stream. The
    turn is not cancelled when the client leaves: the answer is still stored.
    """
    task = asyncio.create_task(turn())
    started = False
    while True:
        getter = asyncio.create_task(events.queue.get())
        await asyncio.wait({getter, task}, return_when=asyncio.FIRST_COMPLETED)
        if getter.done():
            started = True
            yield getter.result()
            continue
        getter.cancel()
        while not events.queue.empty():
            started = True
            yield events.queue.get_nowait()
        break
    error = task.exception()
    if error is None:
        result = task.result()
        yield TurnEvent("done", {}, result=result)
        return
    if not started:
        raise error
    yield TurnEvent("error", _error_data(error))


def _error_data(error: BaseException) -> dict[str, Any]:
    """The problem fields of an error (`common/internal` for a crash)."""
    if isinstance(error, BaseError):
        return {
            "type": error.code,
            "title": error.support_details,
            "message_key": error.message_key,
            "params": dict(error.params),
        }
    log.error("ai.turn_stream_failed", error=repr(error))
    return {"type": "common/internal", "title": "Internal error"}
