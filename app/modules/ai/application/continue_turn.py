"""The model/tool loop of one turn (AI-2, AI-8, AI-9)."""

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from app.modules.ai.application.assistant_profile import profile_for
from app.modules.ai.application.budget import BudgetService, LimitHit
from app.modules.ai.application.history_summarizer import HistorySummarizer
from app.modules.ai.application.system_prompts import SystemPrompts
from app.modules.ai.application.tool_runner import ToolRunner
from app.modules.ai.application.tools.base import ToolContext
from app.modules.ai.application.tools.registry import ToolRegistry
from app.modules.ai.application.views import TurnStatus
from app.modules.ai.domain.chat import (
    Chat,
    ChatMessage,
    MessageContent,
    MessageRole,
    last_turn,
)
from app.modules.ai.domain.errors import ChatNotFoundError, NothingToRegenerateError
from app.modules.ai.domain.history import (
    SUMMARY_EVERY,
    WINDOW_MESSAGES,
    select_window,
    to_llm_messages,
)
from app.modules.ai.domain.tool_call import ToolCall, ToolStatus
from app.modules.ai.ports.unit_of_work import AiUnitOfWork
from app.settings import Settings
from app.shared.actor import Actor
from app.shared.clock import Clock
from app.shared.contracts.ai import LlmGateway
from app.shared.contracts.web_search import WebResult
from app.shared.i18n.core import I18nCore
from app.shared.ids import new_id
from app.shared.limits import LimitsProvider, StaticLimits
from app.shared.web_citations import rewrite_markers

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
        prompts: SystemPrompts,
        clock: Clock,
        settings: Settings,
        i18n: I18nCore,
        limits: LimitsProvider | None = None,
    ) -> None:
        """Store the collaborators."""
        self.prompts = prompts
        self.uow_factory = uow_factory
        self.limits = limits or StaticLimits(settings.limits)
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
        ctx = ToolContext(actor, chat_id, locale, scope=chat.scope)
        run = _Run(chat_id, ctx, summary, after, progress)
        steps = profile_for(
            chat.assistant,
            self.settings,
            chat.tier,
            limits=await self.limits.current(),
        ).max_tool_steps
        for _ in range(steps):
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
        system = await self.prompts.build(chat, run.ctx.locale)
        window = select_window(tail, run.after_seq)
        messages = to_llm_messages(window, run.summary)
        tools = self.registry.llm_tools(chat.assistant)
        if await self._over_budget(chat, system, messages, tools):
            return TurnStatus.LIMIT_REACHED
        task = profile_for(chat.assistant, self.settings, chat.tier).llm
        response = await self.llm.complete(
            model=chat.model,
            system=system,
            messages=messages,
            tools=tools,
            max_tokens=task.output_tokens(MAX_OUTPUT_TOKENS),
            provider=task.provider(),
            tuning=task.tuning,
        )
        usage = response.get("usage") or {}
        tokens_in, tokens_out = int(usage.get("input", 0)), int(usage.get("output", 0))
        await self.budget.add(
            chat.owner_id, (tokens_in + tokens_out) * self._weight(chat), chat.assistant
        )
        taken = {call.id for message in tail for call in message.tool_calls}
        calls = await self.runner.propose(
            chat.assistant, run.ctx, response.get("tool_calls") or [], taken
        )
        message, stored = await self._store(
            run.chat_id,
            str(response.get("text") or ""),
            calls,
            (tokens_in, tokens_out),
            web=_turn_web(tail),
        )
        run.progress.changed.append(message)
        run.progress.chat = stored
        return _final_status(calls)

    async def precheck(self, chat: Chat, text: str, locale: str) -> LimitHit | None:
        """Return the limit a new user message would run into, before it is stored."""
        _, tail = await self._load(chat.id)
        window = select_window(tail[-WINDOW_MESSAGES:], 0)
        messages = [*to_llm_messages(window), {"role": "user", "content": text}]
        system = await self.prompts.build(chat, locale)
        tools = self.registry.llm_tools(chat.assistant)
        return await self._check(chat, system, messages, tools)

    async def precheck_replay(self, chat: Chat, locale: str) -> LimitHit | None:
        """Return the limit answering the last user message again would run into."""
        _, tail = await self._load(chat.id)
        turn = last_turn(tail)
        if turn is None:
            raise NothingToRegenerateError()
        history = tail[: len(tail) - len(turn[1])]
        window = select_window(history[-WINDOW_MESSAGES:], 0)
        system = await self.prompts.build(chat, locale)
        tools = self.registry.llm_tools(chat.assistant)
        return await self._check(chat, system, to_llm_messages(window), tools)

    def _weight(self, chat: Chat) -> int:
        """Return how many budget tokens one model token of this chat costs."""
        return profile_for(chat.assistant, self.settings, chat.tier).weight

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
        estimate = (len(request) // 3 + MAX_OUTPUT_TOKENS) * self._weight(chat)
        return await self.budget.check(chat.owner_id, chat.assistant, estimate)

    async def _store(
        self,
        chat_id: UUID,
        text: str,
        calls: list[ToolCall],
        tokens: tuple[int, int],
        web: list[WebResult] | None = None,
    ) -> tuple[ChatMessage, Chat]:
        now = self.clock.now()
        content = _answer_content(text, web or [])
        async with self.uow_factory() as uow:
            chat = await uow.chats.get_for_update(chat_id)
            if chat is None:
                raise ChatNotFoundError()
            message = ChatMessage(
                id=new_id(),
                chat_id=chat_id,
                seq=await uow.messages.last_seq(chat_id) + 1,
                role=MessageRole.ASSISTANT,
                content=content,
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


def _turn_web(tail: list[ChatMessage]) -> list[WebResult]:
    """The web results of the user message this turn answers."""
    for message in reversed(tail):
        if message.role is MessageRole.USER:
            return message.content.web
    return []


def _answer_content(text: str, web: list[WebResult]) -> MessageContent:
    """The answer with `[[W1]]` markers turned into chips, used pages marked."""
    if not web:
        return MessageContent(text=text)
    chips, used = rewrite_markers(text, len(web))
    shown = [result.model_copy(update={"cited": result.n in used}) for result in web]
    return MessageContent(text=chips, web=shown)


def _final_status(calls: list[ToolCall]) -> TurnStatus | None:
    if any(c.status is ToolStatus.PENDING_APPROVAL for c in calls):
        return TurnStatus.AWAITING_APPROVAL
    if not calls:
        return TurnStatus.DONE
    return None
