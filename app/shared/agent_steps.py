"""Agent steps: the ordered trace of what one answer did (AI-STEPS).

A step is one visible action of the assistant while it answers: a file it read, a web
search, a retrieval hop, a tool call, a view it opened, a thing it created. The answer
pipelines (ai chats, notebook chat) open a `StepRecorder` with `recording()`; any code
below them (tools, retrieval, the query decomposer) emits steps with `record_step()`
or `async with step(...)` without knowing who listens. Without a recorder these calls
do nothing. The recorded steps are stored with the assistant message and shown in
the chat; they never go back to the model (`steps_note` is the most it may see).
"""

import time
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from enum import StrEnum
from typing import Final

from app.shared.ids import new_id

from pydantic import BaseModel

LABEL_MAX_CHARS: Final = 120
TARGET_MAX_CHARS: Final = 200
NOTE_MAX_STEPS: Final = 8


class StepKind(StrEnum):
    """What a step did; the web picks the icon from it."""

    READ_FILE = "read_file"
    WEB_SEARCH = "web_search"
    RETRIEVE = "retrieve"
    OPEN_VIEW = "open_view"
    CREATE = "create"
    TOOL = "tool"
    THINK = "think"


class StepStatus(StrEnum):
    """Where a step is."""

    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class AgentStep(BaseModel):
    """One step: `target` is a shown name (a file), `ref` an id the web can open."""

    id: str
    kind: StepKind
    label: str
    target: str | None = None
    ref: str | None = None
    status: StepStatus = StepStatus.RUNNING
    started_at: datetime | None = None
    duration_ms: int | None = None


StepListener = Callable[[AgentStep], None]


class StepRecorder:
    """Collects the steps of one answer in order and tells a live listener."""

    def __init__(self, listener: StepListener | None = None) -> None:
        """Start empty; `listener` gets a copy of every new or changed step."""
        self.listener = listener
        self._steps: list[AgentStep] = []
        self._started: dict[str, float] = {}
        self._updates: list[AgentStep] = []

    @property
    def steps(self) -> list[AgentStep]:
        """The steps so far, oldest first."""
        return list(self._steps)

    def start(
        self,
        kind: StepKind,
        label: str,
        *,
        target: str | None = None,
        ref: str | None = None,
    ) -> AgentStep:
        """Open a running step and return it."""
        made = self._make(kind, label, target=target, ref=ref)
        self._steps.append(made)
        self._started[made.id] = time.monotonic()
        self._publish(made)
        return made

    def _make(
        self,
        kind: StepKind,
        label: str,
        *,
        target: str | None,
        ref: str | None,
        status: StepStatus = StepStatus.RUNNING,
    ) -> AgentStep:
        return AgentStep(
            id=new_id().hex[-12:],
            kind=kind,
            label=label.strip()[:LABEL_MAX_CHARS],
            target=target[:TARGET_MAX_CHARS] if target else None,
            ref=ref,
            status=status,
            started_at=datetime.now(UTC),
        )

    def finish(self, step_id: str, status: StepStatus = StepStatus.DONE) -> None:
        """Close a step with its status and duration (an unknown id is ignored)."""
        for index, item in enumerate(self._steps):
            if item.id == step_id:
                began = self._started.pop(step_id, time.monotonic())
                elapsed = int((time.monotonic() - began) * 1000)
                done = item.model_copy(
                    update={"status": status, "duration_ms": elapsed}
                )
                self._steps[index] = done
                self._publish(done)
                return

    def add(
        self,
        kind: StepKind,
        label: str,
        *,
        target: str | None = None,
        ref: str | None = None,
        status: StepStatus = StepStatus.DONE,
    ) -> AgentStep:
        """Record a step that is already over (published once, finished)."""
        made = self._make(kind, label, target=target, ref=ref, status=status)
        made = made.model_copy(update={"duration_ms": 0})
        self._steps.append(made)
        self._publish(made)
        return made

    def pop_updates(self) -> list[AgentStep]:
        """The updates since the last call (a stream sends each once)."""
        updates, self._updates = self._updates, []
        return updates

    def take(self) -> list[AgentStep]:
        """Return the steps and forget them (they belong to one stored message)."""
        steps, self._steps = self._steps, []
        return steps

    def _publish(self, item: AgentStep) -> None:
        self._updates.append(item)
        if self.listener is not None:
            self.listener(item)


_CURRENT: ContextVar[StepRecorder | None] = ContextVar("agent_steps", default=None)


def current_steps() -> StepRecorder | None:
    """The recorder of the answer being made, None outside one."""
    return _CURRENT.get()


@contextmanager
def recording(recorder: StepRecorder) -> Iterator[StepRecorder]:
    """Make `recorder` the one `record_step` and `step` write to."""
    token = _CURRENT.set(recorder)
    try:
        yield recorder
    finally:
        try:
            _CURRENT.reset(token)
        except ValueError:  # a stream ends in another task than it started in
            _CURRENT.set(None)


def record_step(
    kind: StepKind,
    label: str,
    *,
    target: str | None = None,
    ref: str | None = None,
    status: StepStatus = StepStatus.DONE,
) -> None:
    """Record a finished step, if an answer is being recorded."""
    recorder = _CURRENT.get()
    if recorder is not None:
        recorder.add(kind, label, target=target, ref=ref, status=status)


@asynccontextmanager
async def step(
    kind: StepKind,
    label: str,
    *,
    target: str | None = None,
    ref: str | None = None,
) -> AsyncIterator[None]:
    """Record a step around a block: running, then done or failed."""
    recorder = _CURRENT.get()
    if recorder is None:
        yield
        return
    made = recorder.start(kind, label, target=target, ref=ref)
    try:
        yield
    except BaseException:
        recorder.finish(made.id, StepStatus.FAILED)
        raise
    recorder.finish(made.id)


def steps_note(steps: list[AgentStep]) -> str:
    """A one-line note of the steps for a model, "" when there are none."""
    parts = [
        f"{item.label} ({item.target})" if item.target else item.label
        for item in steps[:NOTE_MAX_STEPS]
    ]
    return f"[Steps: {'; '.join(parts)}]" if parts else ""
