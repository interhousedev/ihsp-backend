"""Live events of one turn for the streaming variant of the chat endpoints.

The turn runs in a task of its own and puts events on a queue: `step` (a step
started or finished), `status` (the line the pending answer shows), `delta` (a
piece of the text the model is writing), `round_end` (that text was a progress
note before tool calls, not the answer), then `done` (the result) or `error`.
"""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Coroutine
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


AbandonedHook = Callable[[TurnResultView], Awaitable[None]]
_background: set[asyncio.Task[None]] = set()


async def run_streamed(
    events: TurnEvents,
    turn: Callable[[], Coroutine[Any, Any, TurnResultView]],
    on_abandoned: AbandonedHook | None = None,
) -> AsyncIterator[TurnEvent]:
    """Run `turn` and yield its events, then `done` or `error`.

    An error before the first event (a refusal: limit, unknown chat) is raised, so
    the endpoint can answer with a plain problem response instead of a stream. The
    turn is not cancelled when the client leaves: the answer is still stored, and
    `on_abandoned` gets its result once, when the client left before `done` was
    delivered (a failed turn is not reported).
    """
    task = asyncio.create_task(turn())
    started = False
    delivered = False
    try:
        async for event in _drain(events, task):
            started = True
            yield event
        error = task.exception()
        if error is None:
            yield TurnEvent("done", {}, result=task.result())
            delivered = True
            return
        if not started:
            raise error
        delivered = True  # nothing to announce: the turn failed
        yield TurnEvent("error", _error_data(error))
    finally:
        if not delivered and on_abandoned is not None:
            _announce_when_done(task, on_abandoned)


async def _drain(
    events: TurnEvents, task: "asyncio.Task[TurnResultView]"
) -> AsyncIterator[TurnEvent]:
    """Yield queued events until `task` ends, then the ones left in the queue."""
    while True:
        getter = asyncio.create_task(events.queue.get())
        try:
            await asyncio.wait({getter, task}, return_when=asyncio.FIRST_COMPLETED)
        except BaseException:
            getter.cancel()
            raise
        if getter.done():
            yield getter.result()
            continue
        getter.cancel()
        while not events.queue.empty():
            yield events.queue.get_nowait()
        return


def _announce_when_done(
    task: "asyncio.Task[TurnResultView]", hook: AbandonedHook
) -> None:
    """Call `hook` with the result of `task` once it ends well."""

    def finished(done: "asyncio.Task[TurnResultView]") -> None:
        if done.cancelled() or done.exception() is not None:
            return
        notice = asyncio.ensure_future(_guarded(hook, done.result()))
        _background.add(notice)
        notice.add_done_callback(_background.discard)

    task.add_done_callback(finished)


async def _guarded(hook: AbandonedHook, result: TurnResultView) -> None:
    """Run the hook; its failure is logged, never raised into the loop."""
    try:
        await hook(result)
    except Exception as exc:
        log.warning("ai.turn_abandoned_hook_failed", error_type=type(exc).__name__)


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
