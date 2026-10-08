"""The model/tool loop of one turn (AI-2, AI-8, AI-9)."""

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from app.modules.ai.application.budget import BudgetService, LimitHit
from app.modules.ai.application.history_summarizer import HistorySummarizer
from app.modules.ai.application.tool_runner import ToolRunner
from app.modules.ai.application.tools.base import ToolContext
from app.modules.ai.application.tools.registry import ToolRegistry
from app.modules.ai.application.views import TurnStatus
from app.modules.ai.domain.chat import (
    Chat,
    ChatMessage,
    MessageContent,
    MessageRole,
)
from app.modules.ai.domain.errors import ChatNotFoundError
from app.modules.ai.domain.history import (
    SUMMARY_EVERY,
    WINDOW_MESSAGES,
    select_window,
    to_llm_messages,
)
from app.modules.ai.domain.prompts import system_prompt
from app.modules.ai.domain.tool_call import ToolCall, ToolStatus
from app.modules.ai.ports.unit_of_work import AiUnitOfWork
from app.settings import Settings
from app.shared.actor import Actor
from app.shared.clock import Clock, local_today
from app.shared.contracts.ai import LlmGateway
from app.shared.i18n.core import I18nCore
from app.shared.ids import new_id

MAX_OUTPUT_TOKENS = 4096
TAIL_MESSAGES = WINDOW_MESSAGES + SUMMARY_EVERY + 20


@dataclass(slots=True)
class TurnProgress:
    """What a turn did: the chat, the messages it created or changed, the end state."""

    chat: Chat
    changed: list[ChatMessage] = field(default_factory=list)
    status: TurnStatus = TurnStatus.DONE


@dataclass(slots=True)
class _Run:
    """State shared by the steps of one turn."""

    chat_id: UUID
    ctx: ToolContext
    summary: str | None
    after_seq: int
    progress: TurnProgress


class ContinueTurn:
    """Calls the model until it answers, a write needs approval or a limit hits."""

    def __init__(
        self,
        *,
        uow_factory: Callable[[], AiUnitOfWork],
        llm: LlmGateway,
        registry: ToolRegistry,
        runner: ToolRunner,
        budget: BudgetService,
        summarizer: HistorySummarizer,
        clock: Clock,
        settings: Settings,
        i18n: I18nCore,
    ) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
        self.llm = llm
        self.registry = registry
        self.runner = runner
        self.budget = budget
        self.summarizer = summarizer
        self.clock = clock
        self.settings = settings
        self.i18n = i18n

    async def execute(
        self,
        *,
        chat_id: UUID,
        actor: Actor,
        locale: str,
        changed: list[ChatMessage] | None = None,
    ) -> TurnProgress:
        """Run model steps; `changed` carries messages the caller already touched."""
        chat, tail = await self._load(chat_id)
        summary, after = await self.summarizer.context(
            chat, tail[-1].seq if tail else 0
        )
        progress = TurnProgress(chat=chat, changed=list(changed or []))
        run = _Run(
            chat_id, ToolContext(actor, chat_id, locale), summary, after, progress
        )
        for _ in range(self.settings.limits.ai_max_tool_steps):
            status = await self._step(run)
            if status is not None:
                progress.status = status
                return progress
        await self._close_with_notice(run)
        return progress

    async def _load(self, chat_id: UUID) -> tuple[Chat, list[ChatMessage]]:
        async with self.uow_factory() as uow:
            chat = await uow.chats.get(chat_id)
            if chat is None or chat.deleted_at is not None:
                raise ChatNotFoundError()
            return chat, await uow.messages.list_tail(chat_id, TAIL_MESSAGES)

    async def _step(self, run: _Run) -> TurnStatus | None:
        """Do one model request; return the final status or None to continue."""
        chat, tail = await self._load(run.chat_id)
        system = system_prompt(chat.assistant, run.ctx.locale, local_today(self.clock))
        window = select_window(tail, run.after_seq)
        messages = to_llm_messages(window, run.summary)
        tools = self.registry.llm_tools(chat.assistant)
        if await self._over_budget(chat, system, messages, tools):
            return TurnStatus.LIMIT_REACHED
        response = await self.llm.complete(
            model=chat.model,
            system=system,
            messages=messages,
            tools=tools,
            max_tokens=MAX_OUTPUT_TOKENS,
        )
        usage = response.get("usage") or {}
        tokens_in, tokens_out = int(usage.get("input", 0)), int(usage.get("output", 0))
        await self.budget.add(chat.owner_id, tokens_in + tokens_out)
        taken = {call.id for message in tail for call in message.tool_calls}
        calls = await self.runner.propose(
            chat.assistant, run.ctx, response.get("tool_calls") or [], taken
        )
        message, stored = await self._store(
            run.chat_id, str(response.get("text") or ""), calls, (tokens_in, tokens_out)
        )
        run.progress.changed.append(message)
        run.progress.chat = stored
        return _final_status(calls)

    async def precheck(self, chat: Chat, text: str, locale: str) -> LimitHit | None:
        """Return the limit a new user message would run into, before it is stored."""
        _, tail = await self._load(chat.id)
        window = select_window(tail[-WINDOW_MESSAGES:], 0)
        messages = [*to_llm_messages(window), {"role": "user", "content": text}]
        system = system_prompt(chat.assistant, locale, local_today(self.clock))
        tools = self.registry.llm_tools(chat.assistant)
        return await self._check(chat, system, messages, tools)

    async def _over_budget(
        self,
        chat: Chat,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> bool:
        return await self._check(chat, system, messages, tools) is not None

    async def _check(
        self,
        chat: Chat,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> LimitHit | None:
        request = json.dumps(
            {"system": system, "messages": messages, "tools": tools},
            ensure_ascii=False,
        )
        estimate = len(request) // 3 + MAX_OUTPUT_TOKENS
        return await self.budget.check(chat.owner_id, chat.assistant, estimate)

    async def _store(
        self,
        chat_id: UUID,
        text: str,
        calls: list[ToolCall],
        tokens: tuple[int, int],
    ) -> tuple[ChatMessage, Chat]:
        now = self.clock.now()
        async with self.uow_factory() as uow:
            chat = await uow.chats.get_for_update(chat_id)
            if chat is None:
                raise ChatNotFoundError()
            message = ChatMessage(
                id=new_id(),
                chat_id=chat_id,
                seq=await uow.messages.last_seq(chat_id) + 1,
                role=MessageRole.ASSISTANT,
                content=MessageContent(text=text),
                created_at=now,
                tool_calls=calls,
                tokens_in=tokens[0],
                tokens_out=tokens[1],
            )
            await uow.messages.add(message)
            chat.pending_approvals += sum(
                1 for c in calls if c.status is ToolStatus.PENDING_APPROVAL
            )
            chat.last_message_at = now
            await uow.chats.save(chat)
            await uow.commit()
        return message, chat

    async def _close_with_notice(self, run: _Run) -> None:
        """After the last allowed step, end the turn with a short assistant note."""
        text = self.i18n.t(run.ctx.locale, "ai-step-limit")
        message, chat = await self._store(run.chat_id, text, [], (0, 0))
        run.progress.changed.append(message)
        run.progress.chat = chat


def _final_status(calls: list[ToolCall]) -> TurnStatus | None:
    if any(c.status is ToolStatus.PENDING_APPROVAL for c in calls):
        return TurnStatus.AWAITING_APPROVAL
    if not calls:
        return TurnStatus.DONE
    return None
