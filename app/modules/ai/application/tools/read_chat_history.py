"""Tool: older messages of the current chat, on demand (AI-EFF-3).

Only the newest `ai_chat_history_limit` messages go to the model with each request;
this tool lets the model read earlier ones. It reads the chat the tool runs in and
nothing else, and only for the chat's owner.
"""

from collections.abc import Callable, Sequence
from typing import Any

from app.modules.ai.application.tools.base import ReadTool, ToolContext
from app.modules.ai.domain.chat import ChatMessage
from app.modules.ai.domain.errors import ChatNotFoundError
from app.modules.ai.domain.tool_args import ToolArgs
from app.modules.ai.ports.unit_of_work import AiUnitOfWork

from pydantic import Field

PAGE_MAX = 20
SCAN_MESSAGES = 400  # a search reads at most this many of the newest messages
TEXT_CHARS = 2000


class ReadChatHistoryArgs(ToolArgs):
    """Which messages: `offset` back from the newest, at most `limit`, a filter."""

    offset: int = Field(default=0, ge=0, le=100_000)
    limit: int = Field(default=10, ge=1, le=PAGE_MAX)
    query: str | None = Field(default=None, min_length=1, max_length=200)


def _row(message: ChatMessage) -> dict[str, Any]:
    return {
        "seq": message.seq,
        "role": message.role.value,
        "text": message.text[:TEXT_CHARS],
    }


def _matches(
    messages: Sequence[ChatMessage], args: ReadChatHistoryArgs
) -> tuple[list[ChatMessage], bool]:
    """Matching messages, newest first, skipping `offset` matches; more left?"""
    needle = (args.query or "").casefold()
    found = [m for m in reversed(messages) if needle in m.text.casefold()]
    end = args.offset + args.limit
    return found[args.offset : end], len(found) > end


class ReadChatHistory(ReadTool[ReadChatHistoryArgs]):
    """Earlier messages of this chat."""

    name = "read_chat_history"
    description = (
        "Read earlier messages of this conversation that are not in your context. "
        "offset counts back from the newest message (0 = newest), limit is at most "
        f"{PAGE_MAX}; query keeps only messages containing that text. Returns seq, "
        "role and text, oldest first."
    )
    args_model = ReadChatHistoryArgs

    def __init__(self, uow_factory: Callable[[], AiUnitOfWork]) -> None:
        """Store the unit of work factory."""
        self.uow_factory = uow_factory

    async def run(self, args: ReadChatHistoryArgs, ctx: ToolContext) -> dict[str, Any]:
        """Return a bounded page of the caller's own chat."""
        async with self.uow_factory() as uow:
            chat = await uow.chats.get(ctx.chat_id)
            if chat is None or chat.owner_id != ctx.actor.user_id:
                raise ChatNotFoundError()
            total = await uow.messages.last_seq(ctx.chat_id)
            if args.query:
                tail = await uow.messages.list_tail(ctx.chat_id, SCAN_MESSAGES)
                matched, more = _matches(tail, args)
                page = sorted(matched, key=lambda m: m.seq)
            else:
                up_to = max(total - args.offset, 0)
                page = await uow.messages.list_range(
                    ctx.chat_id,
                    after_seq=max(up_to - args.limit, 0),
                    up_to_seq=up_to,
                )
                more = bool(page) and page[0].seq > 1
        return {"total": total, "messages": [_row(m) for m in page], "has_more": more}
