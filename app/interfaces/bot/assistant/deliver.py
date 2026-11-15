"""Play a turn's events into Telegram: the streamed answer, approvals, files."""

import re
from typing import Any
from uuid import UUID

from app.interfaces.bot.assistant.render import Chunk, render_final
from app.interfaces.bot.assistant.service import BotAssistant, Events
from app.interfaces.bot.assistant.stream import AnswerStream
from app.interfaces.bot.utilities.html import escape
from app.interfaces.bot.widgets.deliver import WidgetPlan, plan_widgets, send_widgets
from app.modules.ai.application.tools.show_ui_block import SHOW_UI_BLOCK
from app.shared.i18n.core import I18nContext
from app.shared.openui.blocks import fenced
from app.shared.openui.degrade import degrade_blocks_last
from app.shared.openui.visual import has_valid_blocks

import structlog
from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.filters.callback_data import CallbackData
from aiogram.types import BufferedInputFile, InlineKeyboardButton

log = structlog.get_logger(__name__)

PENDING = "pending_approval"
MAX_IMAGES = 5
IMAGE = re.compile(r"!\[[^\]]*\]\((https?://[^\s)]+)\)")


class AiCallCb(CallbackData, prefix="ai"):
    """Approve (ok) or cancel a write the assistant proposed; token from the store."""

    token: str
    ok: bool


class AiVizCb(CallbackData, prefix="aiv"):
    """Create the 7-day share of an answer with OpenUI blocks; token from the store."""

    token: str


async def _visual_rows(
    assistant: BotAssistant,
    user_id: UUID,
    chat_id: UUID,
    answer: Any | None,
    body: str,
    i18n: I18nContext,
) -> list[list[InlineKeyboardButton]]:
    """The "See visualization" button when the answer has a valid OpenUI block.

    The share is created lazily, on the press (see handlers/visualize.py).
    """
    seq = getattr(answer, "seq", None)
    if not isinstance(seq, int) or not has_valid_blocks(body):
        return []
    token = await assistant.store.remember_visual(user_id, chat_id, seq)
    return [
        [
            InlineKeyboardButton(
                text=i18n("bot-ai-visualization"),
                callback_data=AiVizCb(token=token).pack(),
            )
        ]
    ]


async def _widget_plan(
    assistant: BotAssistant,
    stream: AnswerStream,
    user_id: UUID,
    chat_id: UUID,
    answer: Any | None,
    body: str,
    i18n: I18nContext,
) -> WidgetPlan | None:
    """Widgets for a private chat's answer when the flag is on and all blocks fit."""
    seq = getattr(answer, "seq", None)
    if not assistant.widgets or stream.chat_id <= 0 or not isinstance(seq, int):
        return None
    if not has_valid_blocks(body):
        return None
    token = await assistant.store.remember_visual(user_id, chat_id, seq)
    return plan_widgets(
        body, viz_token=token, visualize_label=i18n("bot-ai-visualization")
    )


def _answer(result: Any) -> Any | None:
    """The newest assistant message of the turn."""
    messages = [m for m in result.new_messages if str(m.role) == "assistant"]
    return messages[-1] if messages else None


def _card(call: Any) -> str:
    """The approval card of a pending call as HTML."""
    preview = call.preview
    if preview is None:
        return f"<b>{escape(call.tool)}</b>"
    lines = [f"<b>{escape(preview.title)}</b>"]
    for item in preview.fields:
        value = "•••" if item.sensitive else item.value
        lines.append(f"{escape(item.label)}: {escape(value)}")
    lines.extend(f"• {escape(entry)}" for entry in preview.items)
    return "\n".join(lines)


async def _approval_rows(
    assistant: BotAssistant,
    user_id: UUID,
    chat_id: UUID,
    calls: list[Any],
    i18n: I18nContext,
) -> list[list[InlineKeyboardButton]]:
    rows: list[list[InlineKeyboardButton]] = []
    for call in calls:
        token = await assistant.store.remember_call(user_id, chat_id, call.id)
        rows.append(
            [
                InlineKeyboardButton(
                    text=i18n("bot-ai-approve"),
                    callback_data=AiCallCb(token=token, ok=True).pack(),
                ),
                InlineKeyboardButton(
                    text=i18n("bot-ai-cancel"),
                    callback_data=AiCallCb(token=token, ok=False).pack(),
                ),
            ]
        )
    return rows


async def _send_documents(
    bot: Bot,
    chat: int,
    assistant: BotAssistant,
    calls: list[Any],
    thread: int | None,
) -> None:
    for call in calls:
        document = getattr(call, "document", None)
        if document is None or call.status != "done":
            continue
        data = await assistant.files.read_bytes(document.file_id)
        await bot.send_document(
            chat,
            BufferedInputFile(data, filename=document.name),
            message_thread_id=thread,
        )


async def _send_images(bot: Bot, chat: int, markdown: str, thread: int | None) -> None:
    for url in list(dict.fromkeys(IMAGE.findall(markdown)))[:MAX_IMAGES]:
        try:
            await bot.send_photo(chat, url, message_thread_id=thread)
        except TelegramAPIError:
            log.info("bot.ai.image_failed", url=url)


def _error_text(data: dict[str, Any], i18n: I18nContext) -> str:
    key = data.get("message_key") or "bot-error-generic"
    return escape(i18n.get(key, **(data.get("params") or {})))


async def _consume(
    stream: AnswerStream, events: Events
) -> tuple[str, Any, dict[str, Any] | None]:
    """Drain the events: the streamed text, the final result and any error."""
    text, result, failure = "", None, None
    async for event in events:
        if event.name == "delta":
            text += str(event.data.get("text", ""))
            await stream.update(text)
        elif event.name == "round_end":
            text = ""  # a progress note before tool calls, not the answer
        elif event.name == "done":
            result = event.result
        elif event.name == "error":
            failure = event.data
        else:
            await stream.typing()
    return text, result, failure


def _ui_blocks(calls: list[Any]) -> list[str]:
    """The sources of the blocks the model showed with the `show_ui_block` tool."""
    return [
        str(call.ui_block)
        for call in calls
        if call.tool == SHOW_UI_BLOCK
        and str(call.status) == "done"
        and getattr(call, "ui_block", None)
    ]


def _tool_widgets(
    assistant: BotAssistant, stream: AnswerStream, sources: list[str]
) -> tuple[list[WidgetPlan], list[str]]:
    """Tool blocks as widgets (flag on, private chat) and those left for the text."""
    plans: list[WidgetPlan] = []
    rest: list[str] = []
    for source in sources:
        plan = None
        if assistant.widgets and stream.chat_id > 0:
            plan = plan_widgets(fenced(source), viz_token=None, visualize_label="")
        if plan is None:
            rest.append(source)
        else:
            plans.append(plan)
    return plans, rest


def _made_calls(result: Any) -> list[Any]:
    return [
        call
        for message in result.new_messages
        if str(message.role) == "assistant"
        for call in message.tool_calls
    ]


async def deliver(
    bot: Bot,
    stream: AnswerStream,
    events: Events,
    *,
    assistant: BotAssistant,
    user_id: UUID,
    chat_id: UUID,
    i18n: I18nContext,
) -> None:
    """Stream the answer text; finish with the UI blocks at its end, then files.

    The blocks (from the `show_ui_block` tool or written in the text) close the
    answer message as Markdown; with widgets on they are widget messages instead.
    """
    text, result, failure = await _consume(stream, events)
    if result is None:
        await stream.abort()
        await bot.send_message(
            stream.chat_id,
            _error_text(failure or {}, i18n),
            message_thread_id=stream.thread_id,
        )
        return
    answer = _answer(result)
    body = answer.text if answer is not None else text
    calls = list(answer.tool_calls) if answer is not None else []
    pending = [call for call in calls if str(call.status) == PENDING]
    plan = await _widget_plan(assistant, stream, user_id, chat_id, answer, body, i18n)
    widgets, blocks = _tool_widgets(assistant, stream, _ui_blocks(_made_calls(result)))
    text_body = degrade_blocks_last(plan.text if plan is not None else body, blocks)
    chunks = render_final(text_body) if text_body.strip() else []
    chunks.extend(Chunk(_card(call)) for call in pending)
    if not chunks and plan is None and not widgets:
        chunks = [Chunk(escape(i18n("bot-ai-empty")))]
    rows = await _visual_rows(assistant, user_id, chat_id, answer, body, i18n)
    rows += await _approval_rows(assistant, user_id, chat_id, pending, i18n)
    if plan is not None and not chunks and rows:
        chunks = [Chunk(escape(i18n("bot-ai-visualization")))]
    elif not chunks and (plan is not None or widgets):
        await stream.abort()
    await stream.finish(chunks, rows)
    for widget_plan in [plan, *widgets]:
        if widget_plan is not None:
            await send_widgets(bot, stream.chat_id, widget_plan, stream.thread_id)
    await _send_documents(
        bot, stream.chat_id, assistant, _made_calls(result), stream.thread_id
    )
    await _send_images(bot, stream.chat_id, body, stream.thread_id)
