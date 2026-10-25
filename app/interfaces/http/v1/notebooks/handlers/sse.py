"""Server-sent events of the notebook chat (§ 3.3.6): the Accept switch and the body."""

import asyncio
import json
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import aclosing

from app.modules.notebooks.application.views import StreamEvent

from fastapi import Request
from fastapi.responses import StreamingResponse

MEDIA_TYPE = "text/event-stream"
HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
# The event loop keeps only weak references to tasks.
_PUMPS: set[asyncio.Task[None]] = set()


def wants_stream(request: Request) -> bool:
    """Whether the client asked for server-sent events (`Accept: text/event-stream`)."""
    return MEDIA_TYPE in request.headers.get("accept", "")


def frame(event: StreamEvent) -> bytes:
    """One block: the `event:` line, the `data:` line (JSON) and a blank line.

    The use case's `done` carries the answer as `message`; the contract calls it
    `assistant_message` (`NotebookStreamDone`).
    """
    data = event.data
    if event.name == "done":
        rest = {key: value for key, value in data.items() if key != "message"}
        data = {"assistant_message": data["message"], **rest}
    return f"event: {event.name}\ndata: {json.dumps(data, default=str)}\n\n".encode()


async def stream_response(
    events: AsyncGenerator[StreamEvent, None],
) -> StreamingResponse:
    """Answer 200 with the events, once the first one is known.

    The use case refuses (404, 422, 429, 409) before it stores the question, and
    does it when the first event is asked for. Reading that event here makes the
    refusal a plain problem+json response, not a stream.
    """
    first = await anext(events)
    return StreamingResponse(
        _blocks(first, events), media_type=MEDIA_TYPE, headers=HEADERS
    )


async def _blocks(
    first: StreamEvent, events: AsyncGenerator[StreamEvent, None]
) -> AsyncIterator[bytes]:
    """The body: the blocks of the events, which a task of their own produces.

    When the client leaves, the server cancels the task that sends the body, over
    and over until it ends (the cancellation of its scope never stops). The use
    case must not run in that task: it stores the partial answer and frees the
    thread lock while it is being cancelled, and with every wait cancelled again
    the lock would stay taken. The use case runs in `_pump`, which is cancelled
    once, and this task only forwards its blocks.
    """
    queue: asyncio.Queue[bytes | None] = asyncio.Queue()
    queue.put_nowait(frame(first))
    pump = asyncio.create_task(_pump(events, queue))
    _PUMPS.add(pump)
    pump.add_done_callback(_PUMPS.discard)
    try:
        while (block := await queue.get()) is not None:
            yield block
    finally:
        pump.cancel()


async def _pump(
    events: AsyncGenerator[StreamEvent, None], queue: asyncio.Queue[bytes | None]
) -> None:
    """Run the use case: queue the block of each event, then `None` at the end."""
    try:
        async with aclosing(events):
            async for event in events:
                queue.put_nowait(frame(event))
    finally:
        queue.put_nowait(None)
