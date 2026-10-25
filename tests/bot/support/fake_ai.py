"""A scripted stand-in for the AI module's chat use cases (create, send, decide)."""

from collections import deque
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import UUID

from app.modules.ai.application.turn_events import TurnEvent
from app.shared.actor import Actor
from app.shared.ids import new_id

Script = list[TurnEvent] | Exception


def delta(text: str) -> TurnEvent:
    """A piece of the answer."""
    return TurnEvent("delta", {"text": text})


def round_end(text: str) -> TurnEvent:
    """The text so far was a progress note before tool calls."""
    return TurnEvent("round_end", {"text": text})


def call_view(
    call_id: str = "toolu_1",
    *,
    status: str = "pending_approval",
    title: str = "Create a quiz",
    document: Any = None,
) -> SimpleNamespace:
    """A tool call as the chat views show it."""
    preview = SimpleNamespace(
        title=title,
        fields=[SimpleNamespace(label="Notebook", value="Physics", sensitive=False)],
        items=[],
    )
    return SimpleNamespace(
        id=call_id,
        tool="create_artifact",
        access="write",
        status=status,
        note="",
        preview=preview,
        reject_reason=None,
        expires_at=None,
        document=document,
    )


def done(text: str, *, calls: list[SimpleNamespace] | None = None) -> TurnEvent:
    """The end of the turn with the stored assistant message."""
    message = SimpleNamespace(
        seq=2,
        role="assistant",
        text=text,
        file_ids=[],
        tool_calls=calls or [],
        created_at=datetime(2026, 10, 6, tzinfo=UTC),
    )
    status = "awaiting_approval" if calls else "done"
    result = SimpleNamespace(new_messages=[message], status=status)
    return TurnEvent("done", {}, result=result)  # type: ignore[arg-type]


async def _events(script: Script) -> AsyncIterator[TurnEvent]:
    if isinstance(script, Exception):
        raise script
    for event in script:
        yield event


@dataclass
class FakeAi:
    """Records every call; each turn plays the next queued script."""

    chats: list[UUID] = field(default_factory=list)
    sent: list[dict[str, Any]] = field(default_factory=list)
    decided: list[dict[str, Any]] = field(default_factory=list)
    scripts: deque[Script] = field(default_factory=deque)

    def __post_init__(self) -> None:
        """Expose the use cases under the AiServices attribute names."""
        self.create_chat = SimpleNamespace(execute=self._create)
        self.send_message = SimpleNamespace(stream=self._send)
        self.approve_tool_call = SimpleNamespace(stream=self._approve)
        self.reject_tool_call = SimpleNamespace(stream=self._reject)

    def play(self, *scripts: Script) -> None:
        """Queue the events of the next turns."""
        self.scripts.extend(scripts)

    def _next(self) -> AsyncIterator[TurnEvent]:
        script = self.scripts.popleft() if self.scripts else [done("ok")]
        return _events(script)

    async def _create(self, *, actor: Actor, assistant: Any) -> SimpleNamespace:
        chat_id = new_id()
        self.chats.append(chat_id)
        return SimpleNamespace(id=chat_id, assistant=assistant)

    def _send(
        self, *, actor: Actor, chat_id: UUID, text: str, file_ids: list[UUID]
    ) -> AsyncIterator[TurnEvent]:
        self.sent.append({"chat_id": chat_id, "text": text, "file_ids": file_ids})
        return self._next()

    def _approve(
        self, *, actor: Actor, chat_id: UUID, call_id: str
    ) -> AsyncIterator[TurnEvent]:
        self.decided.append({"chat_id": chat_id, "call_id": call_id, "ok": True})
        return self._next()

    def _reject(
        self, *, actor: Actor, chat_id: UUID, call_id: str, reason: str | None
    ) -> AsyncIterator[TurnEvent]:
        self.decided.append({"chat_id": chat_id, "call_id": call_id, "ok": False})
        return self._next()
