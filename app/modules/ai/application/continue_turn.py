"""The model/tool loop of one turn (AI-2, AI-8, AI-9)."""

import json
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Any
from uuid import UUID

from app.modules.ai.application.assistant_profile import profile_for
from app.modules.ai.application.budget import BudgetService, LimitHit
from app.modules.ai.application.history_summarizer import HistorySummarizer
from app.modules.ai.application.system_prompts import SystemPrompts
from app.modules.ai.application.tool_runner import ToolRunner
from app.modules.ai.application.tools.base import ToolContext
from app.modules.ai.application.tools.registry import ToolRegistry
from app.modules.ai.application.turn_events import TurnEvents
from app.modules.ai.application.views import TurnStatus
from app.modules.ai.domain.assistant import Assistant
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
from app.shared.agent_steps import StepKind, current_steps, record_step
from app.shared.ai.answer_language import answer_language
from app.shared.ai.injection import is_rule_attack
from app.shared.ai.narration import (
    NarrationFilter,
    mentions_a_student,
    strip_narration,
    strip_worked_sums,
)
from app.shared.ai.uzbek import normalize_answer
from app.shared.ai_tasks import AiTask
from app.shared.clock import Clock
from app.shared.contracts.ai import LlmGateway, LlmTuning
from app.shared.contracts.web_search import WebResult
from app.shared.i18n.core import I18nCore
from app.shared.ids import new_id
from app.shared.limits import LimitsProvider, StaticLimits
from app.shared.openui.finalize import OpenUiFinalizer, UsageCounter
from app.shared.web_citations import rewrite_markers

MAX_OUTPUT_TOKENS = 4096
STEP_LIMIT_KEY = "ai-step-limit"
RULE_ATTACK_KEY = "ai-rule-attack"
TAIL_MESSAGES = WINDOW_MESSAGES + SUMMARY_EVERY + 20


def history_span(limit: int) -> int:
    """Messages read for a turn whose history limit is `limit` (AI-EFF-3)."""
    return max(TAIL_MESSAGES, limit + SUMMARY_EVERY + 20)


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
    span: int = TAIL_MESSAGES  # messages read per step (AI-EFF-3)
    message_seq: int | None = None  # the one assistant message of this answer
    events: TurnEvents | None = None  # the live events of a streamed turn
    surface: str = "web"  # "telegram" adds the bot's formatting rules to the prompt
    seen: dict[str, ToolCall] = field(default_factory=dict)  # read calls by key
    answer_now: bool = False  # the next model request may not call tools


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
        self.openui = OpenUiFinalizer(  # AI-OPENUI: before the answer is stored
            llm,
            settings.ai_profile(AiTask.OPENUI_REPAIR),
            enabled=settings.ai.openui_enabled,
            convert_tables=True,
        )

    async def execute(
        self,
        *,
        chat_id: UUID,
        actor: Actor,
        locale: str,
        changed: list[ChatMessage] | None = None,
        events: TurnEvents | None = None,
        surface: str = "web",
    ) -> TurnProgress:
        """Run model steps; `changed` carries messages the caller already touched.

        Every model request of the answer goes into one assistant message: the
        texts of the tool rounds become its `progress` notes and the last text is
        the answer. A turn continued after an approval adds to the waiting message.
        """
        limits = await self.limits.current()
        history = limits.ai_chat_history_limit
        chat, tail = await self._load(chat_id)
        summary, after = await self.summarizer.context(
            chat, tail[-1].seq if tail else 0, window=history
        )
        progress = TurnProgress(chat=chat, changed=list(changed or []))
        ctx = ToolContext(actor, chat_id, locale, scope=chat.scope)
        run = _Run(
            chat_id,
            ctx,
            summary,
            after,
            progress,
            history_span(history),
            surface=surface,
        )
        run.events = events
        if tail and tail[-1].role is MessageRole.ASSISTANT:
            run.message_seq = tail[-1].seq
        steps = profile_for(
            chat.assistant, self.settings, chat.tier, limits=limits
        ).max_tool_steps
        asked = _last_user_text(tail)
        if is_rule_attack(asked):  # a fixed refusal: no model, nothing to echo
            progress.status = await self._refuse_rule_attack(run, asked)
            return progress
        for step in range(steps):
            run.answer_now = run.answer_now or step == steps - 1
            status = await self._step(run)
            if status is not None:
                progress.status = status
                return progress
        await self._close_with_notice(run)
        return progress

    async def _load(
        self, chat_id: UUID, span: int = TAIL_MESSAGES
    ) -> tuple[Chat, list[ChatMessage]]:
        async with self.uow_factory() as uow:
            chat = await uow.chats.get(chat_id)
            if chat is None or chat.deleted_at is not None:
                raise ChatNotFoundError()
            return chat, await uow.messages.list_tail(chat_id, span)

    async def _step(self, run: _Run) -> TurnStatus | None:
        """Do one model request; return the final status or None to continue."""
        chat, tail = await self._load(run.chat_id, run.span)
        asked = _last_user_text(tail)
        system = await self.prompts.build(
            chat,
            run.ctx.locale,
            surface=run.surface,
            last_user_text=asked,
            answer_now=run.answer_now,
        )
        window = select_window(tail, run.after_seq)
        messages = to_llm_messages(window, run.summary)
        tools = self._tools(chat)
        if await self._over_budget(chat, system, messages, tools):
            return TurnStatus.LIMIT_REACHED
        task = profile_for(chat.assistant, self.settings, chat.tier).llm
        tuning = task.tuning
        if run.answer_now:
            tuning = replace(tuning or LlmTuning(), answer_only=True)
        request: dict[str, Any] = {
            "model": chat.model,
            "system": system,
            "messages": messages,
            "tools": tools,
            "max_tokens": task.output_tokens(MAX_OUTPUT_TOKENS),
            "provider": task.provider(),
            "tuning": tuning,
        }
        response, text = await self._ask(run, chat, asked, request)
        usage = response.get("usage") or {}
        tokens_in, tokens_out = int(usage.get("input", 0)), int(usage.get("output", 0))
        await self.budget.add(
            chat.owner_id, (tokens_in + tokens_out) * self._weight(chat), chat.assistant
        )
        taken = {call.id for message in tail for call in message.tool_calls}
        raw_calls = response.get("tool_calls") or []
        if run.answer_now:  # a model that still calls tools is not obeyed: turn ends
            raw_calls = []
            text = text if text.strip() else self.i18n.t(run.ctx.locale, STEP_LIMIT_KEY)
        if raw_calls and run.events is not None:  # the streamed text was a note
            run.events.emit("round_end", {"text": text})
            run.events.status(text)
        if raw_calls and text.strip():  # a progress note between tool rounds
            record_step(StepKind.THINK, text)
        if not raw_calls:  # the answer: repair or drop broken OpenUI blocks
            text = await self.openui.finalize(text, count=self._repair_counter(chat))
            text = normalize_answer(strip_worked_sums(text, asked))
        calls = await self.runner.propose(
            chat.assistant, run.ctx, raw_calls, taken, run.seen
        )
        if calls and all(_is_repeated(call) for call in calls):
            run.answer_now = True  # nothing new can come: answer from what is there
        message, stored = await self._store(
            run, text, calls, (tokens_in, tokens_out), web=_turn_web(tail)
        )
        run.progress.changed.append(message)
        run.progress.chat = stored
        return _final_status(calls)

    async def _refuse_rule_attack(self, run: _Run, asked: str) -> TurnStatus:
        """End the turn with the fixed refusal, in the language of the message."""
        language = answer_language(asked, run.ctx.locale)
        text = self.i18n.t(language, RULE_ATTACK_KEY)
        if run.events is not None:
            run.events.emit("delta", {"text": text})
        message, chat = await self._store(run, text, [], (0, 0))
        run.progress.changed.append(message)
        run.progress.chat = chat
        return TurnStatus.DONE

    async def _ask(
        self, run: _Run, chat: Chat, asked: str, request: dict[str, Any]
    ) -> tuple[dict[str, Any], str]:
        """One model request: the response and its text without a leading note."""
        options: dict[str, Any] = {
            "about_student": _about_student(chat, asked),
            "language": answer_language(asked, run.ctx.locale),
        }
        if run.events is None:
            response = await self.llm.complete(**request)
        else:
            guard = NarrationFilter(**options)
            response = await self._streamed(run.events, request, guard)
        text = str(response.get("text") or "")
        return response, strip_narration(text, **options)

    def _tools(self, chat: Chat) -> list[dict[str, Any]]:
        """The tools offered in this chat; the list stays the same within it."""
        return self.registry.llm_tools(
            chat.assistant, in_project=chat.project_id is not None
        )

    async def _streamed(
        self,
        events: TurnEvents,
        request: dict[str, Any],
        guard: NarrationFilter | None = None,
    ) -> dict[str, Any]:
        """One model request through `stream`: text pieces go out as `delta` events.

        `guard` holds back a leading note about the request. Returns the same shape
        as `complete` (text, tool_calls, usage), with the text as the model wrote it.
        """
        pieces: list[str] = []
        last: dict[str, Any] = {}
        async for item in self.llm.stream(**request):
            if item.get("delta"):
                pieces.append(item["delta"])
                out = guard.feed(item["delta"]) if guard else item["delta"]
                if out:
                    events.emit("delta", {"text": out})
            if "usage" in item:
                last = item
        if guard is not None and (out := guard.finish()):
            events.emit("delta", {"text": out})
        return {
            "text": "".join(pieces),
            "tool_calls": last.get("tool_calls") or [],
            "usage": last.get("usage") or {},
        }

    async def precheck(self, chat: Chat, text: str, locale: str) -> LimitHit | None:
        """Return the limit a new user message would run into, before it is stored."""
        _, tail = await self._load(chat.id)
        window = select_window(tail[-WINDOW_MESSAGES:], 0)
        messages = [*to_llm_messages(window), {"role": "user", "content": text}]
        system = await self.prompts.build(chat, locale)
        return await self._check(chat, system, messages, self._tools(chat))

    async def precheck_replay(self, chat: Chat, locale: str) -> LimitHit | None:
        """Return the limit answering the last user message again would run into."""
        _, tail = await self._load(chat.id)
        turn = last_turn(tail)
        if turn is None:
            raise NothingToRegenerateError()
        history = tail[: len(tail) - len(turn[1])]
        window = select_window(history[-WINDOW_MESSAGES:], 0)
        system = await self.prompts.build(chat, locale)
        return await self._check(
            chat, system, to_llm_messages(window), self._tools(chat)
        )

    def _weight(self, chat: Chat) -> int:
        """Return how many budget tokens one model token of this chat costs."""
        return profile_for(chat.assistant, self.settings, chat.tier).weight

    def _repair_counter(self, chat: Chat) -> UsageCounter:
        """Count the tokens of an OpenUI repair in the chat's budget (AI-OPENUI)."""

        async def count(tokens: int) -> None:
            await self.budget.add(
                chat.owner_id, tokens * self._weight(chat), chat.assistant
            )

        return count

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
        run: _Run,
        text: str,
        calls: list[ToolCall],
        tokens: tuple[int, int],
        web: list[WebResult] | None = None,
    ) -> tuple[ChatMessage, Chat]:
        """Add one model request to the answer's message (made by the first one)."""
        now = self.clock.now()
        content = _answer_content(text, web or [])
        if calls:  # text before tool calls is a progress note, never the answer
            content = MessageContent(progress=[content.text], web=content.web)
        if (recorder := current_steps()) is not None:  # AI-STEPS, up to this message
            content.steps = recorder.take()
        async with self.uow_factory() as uow:
            chat = await uow.chats.get_for_update(run.chat_id)
            if chat is None:
                raise ChatNotFoundError()
            message = None
            if run.message_seq is not None:
                message = await uow.messages.get_for_update(
                    run.chat_id, run.message_seq
                )
            if message is None:
                message = ChatMessage(
                    id=new_id(),
                    chat_id=run.chat_id,
                    seq=await uow.messages.last_seq(run.chat_id) + 1,
                    role=MessageRole.ASSISTANT,
                    content=content,
                    created_at=now,
                    tool_calls=calls,
                    tokens_in=tokens[0],
                    tokens_out=tokens[1],
                )
                await uow.messages.add(message)
                run.message_seq = message.seq
            else:
                _add_round(message, content, calls, tokens)
                await uow.messages.save(message)
            chat.pending_approvals += sum(
                1 for c in calls if c.status is ToolStatus.PENDING_APPROVAL
            )
            chat.last_message_at = now
            await uow.chats.save(chat)
            await uow.commit()
        return message, chat

    async def _close_with_notice(self, run: _Run) -> None:
        """After the last allowed step, end the turn with a short assistant note."""
        text = self.i18n.t(run.ctx.locale, STEP_LIMIT_KEY)
        message, chat = await self._store(run, text, [], (0, 0))
        run.progress.changed.append(message)
        run.progress.chat = chat


def _add_round(
    message: ChatMessage,
    content: MessageContent,
    calls: list[ToolCall],
    tokens: tuple[int, int],
) -> None:
    """Add a round; the text so far becomes a progress note.

    `progress[r]` stays the text of round r (a round with calls stored it already).
    """
    rounds = 1 + max((c.round for c in message.tool_calls), default=0)
    if len(message.content.progress) < rounds:
        message.content.progress.append(message.content.text)
    message.content.progress.extend(content.progress)
    index = len(message.content.progress)
    if content.progress:
        index -= 1
    message.content.text = content.text
    if content.web:
        message.content.web = content.web
    message.content.steps.extend(content.steps)
    message.tool_calls.extend(c.model_copy(update={"round": index}) for c in calls)
    message.tokens_in = (message.tokens_in or 0) + tokens[0]
    message.tokens_out = (message.tokens_out or 0) + tokens[1]


def _last_user_text(tail: list[ChatMessage]) -> str:
    """The text of the user message this turn answers."""
    for message in reversed(tail):
        if message.role is MessageRole.USER:
            return message.content.text
    return ""


def _about_student(chat: Chat, asked: str) -> bool:
    """True when "the student" in a leading sentence can only mean the user."""
    return chat.assistant is Assistant.STUDENT and not mentions_a_student(asked)


def _is_repeated(call: ToolCall) -> bool:
    return isinstance(call.result, dict) and "repeated" in call.result


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
