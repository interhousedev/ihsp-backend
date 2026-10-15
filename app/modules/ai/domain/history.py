"""Turning stored chat messages into the message list sent to the model."""

import json
from collections.abc import Sequence
from typing import Any

from app.modules.ai.domain.chat import ChatMessage, MessageRole
from app.modules.ai.domain.tool_call import ToolCall, ToolStatus
from app.modules.ai.domain.tools import MAX_RESULT_CHARS
from app.shared.slash_commands import expand
from app.shared.web_citations import render_web_block

WINDOW_MESSAGES = 30
SUMMARY_EVERY = 20
MAX_HISTORY_CHARS = 240_000
UNTRUSTED = "untrusted_data"

_FIXED_RESULTS: dict[ToolStatus, dict[str, Any]] = {
    ToolStatus.PENDING_APPROVAL: {"pending_approval": True},
    ToolStatus.SUPERSEDED: {
        "error": "superseded by a new message; the action was not run"
    },
    ToolStatus.EXPIRED: {
        "error": "the user did not approve in 24 hours; the action was not run"
    },
    ToolStatus.RUNNING: {"error": "interrupted; the outcome is unknown"},
}


def tool_result_content(call: ToolCall) -> str:
    """Return the string of the `tool` message for one call.

    Real tool output is wrapped as `{"untrusted_data": ...}` (AI-4); outcomes the
    system or the user produced (rejection, expiry) are plain.
    """
    if call.status is ToolStatus.DONE:
        return _wrapped(call.result or {})
    if call.status is ToolStatus.FAILED:
        return json.dumps({"error": call.error or "the tool failed"})
    if call.status is ToolStatus.REJECTED:
        return json.dumps(
            {"rejected": True, "reason": call.reject_reason}, ensure_ascii=False
        )
    return json.dumps(_FIXED_RESULTS[call.status])


def _wrapped(result: dict[str, Any]) -> str:
    text = json.dumps({UNTRUSTED: result}, ensure_ascii=False, default=str)
    if len(text) <= MAX_RESULT_CHARS:
        return text
    cut = {"truncated": True, "first_characters": text[:MAX_RESULT_CHARS]}
    return json.dumps({UNTRUSTED: cut}, ensure_ascii=False)


def _user_text(message: ChatMessage, *, full_web: bool = True) -> str:
    lines = [expand(message.text)]
    lines.extend(
        f"[attached: {a.name} ({a.file_id})]" for a in message.content.attachments
    )
    web = render_web_block(message.content.web, full=full_web)
    if web:
        lines.append(web)
    return "\n".join(lines)


def _assistant_entries(message: ChatMessage) -> list[dict[str, Any]]:
    """The model requests of one answer: each round's text, calls and results."""
    rounds = len(message.content.progress) + 1
    out: list[dict[str, Any]] = []
    for index in range(rounds):
        last = index == rounds - 1
        text = message.text if last else message.content.progress[index]
        calls = [c for c in message.tool_calls if min(c.round, rounds - 1) == index]
        if not calls and not last:
            continue
        out.extend(_round_entries(text, calls))
    return out


def _round_entries(text: str, calls: list[ToolCall]) -> list[dict[str, Any]]:
    entry: dict[str, Any] = {"role": "assistant"}
    if calls:
        entry["content"] = text or None
        entry["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {
                    "name": call.tool,
                    "arguments": json.dumps(call.args, ensure_ascii=False),
                },
            }
            for call in calls
        ]
    else:
        entry["content"] = text or "…"
    results = [
        {
            "role": "tool",
            "tool_call_id": call.id,
            "content": tool_result_content(call),
        }
        for call in calls
    ]
    return [entry, *results]


def to_llm_messages(
    messages: Sequence[ChatMessage], summary: str | None = None
) -> list[dict[str, Any]]:
    """Build the OpenAI-format messages (without the system message)."""
    out: list[dict[str, Any]] = []
    last_user = max(
        (i for i, m in enumerate(messages) if m.role is MessageRole.USER), default=-1
    )
    for index, message in enumerate(messages):
        if message.role is MessageRole.USER:
            text = _user_text(message, full_web=index == last_user)
            out.append({"role": "user", "content": text})
        else:
            out.extend(_assistant_entries(message))
    if summary and out and out[0]["role"] == "user":
        head = "[Summary of the earlier conversation, context only]\n"
        out[0] = {
            "role": "user",
            "content": f"{head}{summary}\n\n[Conversation continues]\n"
            + out[0]["content"],
        }
    return out


def message_chars(message: ChatMessage) -> int:
    """Return the approximate size of a message in the request."""
    size = len(message.text) + sum(map(len, message.content.progress))
    if message.role is MessageRole.USER:
        size += sum(
            len(r.title) + len(r.url) + len(r.snippet) for r in message.content.web
        )
    for call in message.tool_calls:
        size += len(json.dumps(call.args)) + len(tool_result_content(call))
    return size


def select_window(tail: Sequence[ChatMessage], after_seq: int) -> list[ChatMessage]:
    """Pick the messages to send: those after `after_seq`, bounded in size.

    The window starts at a user message so that no tool result is orphaned. When
    the summary boundary cuts a turn, the turn's user message is added back; when
    the size cap trims the window, leading assistant messages are dropped instead.
    """
    window = [m for m in tail if m.seq > after_seq]
    trimmed = False
    while len(window) > 1 and sum(map(message_chars, window)) > MAX_HISTORY_CHARS:
        window.pop(0)
        trimmed = True
    if window and window[0].role is MessageRole.ASSISTANT:
        if trimmed:
            return _skip_to_user(window)
        return _back_to_user(tail, window)
    return window


def _skip_to_user(window: list[ChatMessage]) -> list[ChatMessage]:
    for index, message in enumerate(window):
        if message.role is MessageRole.USER:
            return window[index:]
    return window


def _back_to_user(
    tail: Sequence[ChatMessage], window: list[ChatMessage]
) -> list[ChatMessage]:
    earlier = [m for m in tail if m.seq < window[0].seq and m.role is MessageRole.USER]
    if earlier:
        return [m for m in tail if m.seq >= earlier[-1].seq]
    return _skip_to_user(window)
