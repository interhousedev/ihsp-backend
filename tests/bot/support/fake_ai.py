"""A scripted stand-in for the AI module's chat use cases (create, send, decide)."""

from collections import deque
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID

from app.modules.ai.application.telegram_topics import TelegramTopics
from app.modules.ai.application.turn_events import TurnEvent
from app.modules.ai.domain.chat import title_from_text
from app.shared.actor import Actor
from app.shared.ids import new_id
from tests.fakes.ai.uow import FakeAiStore, fake_uow_factory

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
    tool: str = "create_artifact",
    ui_block: str | None = None,
) -> SimpleNamespace:
    """A tool call as the chat views show it."""
    preview = SimpleNamespace(
        title=title,
        fields=[SimpleNamespace(label="Notebook", value="Physics", sensitive=False)],
        items=[],
    )
    return SimpleNamespace(
        id=call_id,
        tool=tool,
        access="write",
        status=status,
        note="",
        preview=preview,
        reject_reason=None,
        expires_at=None,
        document=document,
        ui_block=ui_block,
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
    transcribed: list[dict[str, Any]] = field(default_factory=list)
    transcripts: deque[str | Exception] = field(default_factory=deque)
    prechecks: list[Actor] = field(default_factory=list)
    precheck_refusal: Exception | None = None
    titles: dict[UUID, str] = field(default_factory=dict)
    deleted: list[UUID] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Expose the use cases under the AiServices attribute names."""
        self.telegram_topics = TelegramTopics(
            cast(Any, fake_uow_factory(FakeAiStore()))
        )
        self.get_chat = SimpleNamespace(execute=self._get)
        self.delete_chat = SimpleNamespace(execute=self._delete)
        self.create_chat = SimpleNamespace(execute=self._create)
        self.list_chats = SimpleNamespace(execute=self._list)
        self.send_message = SimpleNamespace(stream=self._send)
        self.approve_tool_call = SimpleNamespace(stream=self._approve)
        self.reject_tool_call = SimpleNamespace(stream=self._reject)
        self.transcribe_audio = SimpleNamespace(
            execute=self._transcribe, precheck=self._precheck
        )

    async def _precheck(self, actor: Actor) -> None:
        """Record the access and rate check; refuse when a refusal is scripted."""
        self.prechecks.append(actor)
        if self.precheck_refusal is not None:
            raise self.precheck_refusal

    async def _transcribe(
        self,
        actor: Actor,
        *,
        data: bytes,
        duration_ms: int,
    ) -> str:
        """Record the recording; answer the next scripted transcript."""
        self.transcribed.append({"data": data, "duration_ms": duration_ms})
        if not self.transcripts:
            return "transcript"
        item = self.transcripts.popleft()
        if isinstance(item, Exception):
            raise item
        return item

    async def _get(self, *, actor: Actor, chat_id: UUID) -> SimpleNamespace:
        return SimpleNamespace(chat=SimpleNamespace(title=self.titles.get(chat_id)))

    async def _delete(self, *, actor: Actor, chat_id: UUID) -> None:
        self.deleted.append(chat_id)

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

    async def _list(
        self, *, actor: Actor, assistant: Any, cursor: Any, limit: int
    ) -> SimpleNamespace:
        """The newest chats first, deleted ones left out."""
        alive = [c for c in reversed(self.chats) if c not in self.deleted]
        return SimpleNamespace(items=[SimpleNamespace(id=c) for c in alive[:limit]])

    def _send(
        self,
        *,
        actor: Actor,
        chat_id: UUID,
        text: str,
        file_ids: list[UUID],
        surface: str = "web",
    ) -> AsyncIterator[TurnEvent]:
        if text and chat_id not in self.titles:
            self.titles[chat_id] = title_from_text(text)
        self.sent.append(
            {"chat_id": chat_id, "text": text, "file_ids": file_ids, "surface": surface}
        )
        return self._next()

    def _approve(
        self, *, actor: Actor, chat_id: UUID, call_id: str, surface: str = "web"
    ) -> AsyncIterator[TurnEvent]:
        self.decided.append({"chat_id": chat_id, "call_id": call_id, "ok": True})
        return self._next()

    def _reject(
        self,
        *,
        actor: Actor,
        chat_id: UUID,
        call_id: str,
        reason: str | None,
        surface: str = "web",
    ) -> AsyncIterator[TurnEvent]:
        self.decided.append({"chat_id": chat_id, "call_id": call_id, "ok": False})
        return self._next()
