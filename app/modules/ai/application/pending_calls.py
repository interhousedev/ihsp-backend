"""Rules for tool calls that wait for approval (AI-11)."""

from datetime import datetime

from app.modules.ai.domain.chat import Chat, ChatMessage, count_pending
from app.modules.ai.domain.errors import ToolCallNotFoundError
from app.modules.ai.domain.tool_call import ToolCall, ToolStatus
from app.modules.ai.ports.unit_of_work import AiUnitOfWork

SCAN_MESSAGES = 14  # pending calls only live in the last few messages


async def recent_messages(uow: AiUnitOfWork, chat: Chat) -> list[ChatMessage]:
    """Return the messages that can hold pending calls."""
    return await uow.messages.list_tail(chat.id, SCAN_MESSAGES)


async def refresh_counter(uow: AiUnitOfWork, chat: Chat) -> None:
    """Recount the chat's pending approvals from its recent messages."""
    chat.pending_approvals = count_pending(await recent_messages(uow, chat))
    await uow.chats.save(chat)


async def expire_overdue(
    uow: AiUnitOfWork, chat: Chat, now: datetime
) -> list[ChatMessage]:
    """Mark overdue pending calls as expired; return the messages that changed."""
    if chat.pending_approvals <= 0:
        return []
    changed: list[ChatMessage] = []
    for message in await recent_messages(uow, chat):
        overdue = [c for c in message.tool_calls if c.is_overdue(now)]
        for call in overdue:
            call.status = ToolStatus.EXPIRED
        if overdue:
            await uow.messages.save(message)
            changed.append(message)
    if changed:
        await refresh_counter(uow, chat)
    return changed


async def supersede_pending(
    uow: AiUnitOfWork, chat: Chat, now: datetime
) -> list[ChatMessage]:
    """Mark every call still waiting as superseded (a new message arrived)."""
    changed = await expire_overdue(uow, chat, now)
    if chat.pending_approvals <= 0:
        return changed
    for message in await recent_messages(uow, chat):
        waiting = message.pending_calls()
        for call in waiting:
            call.status = ToolStatus.SUPERSEDED
        if waiting:
            await uow.messages.save(message)
            changed.append(message)
    chat.pending_approvals = 0
    await uow.chats.save(chat)
    return changed


async def find_call(
    uow: AiUnitOfWork, chat: Chat, call_id: str
) -> tuple[ChatMessage, ToolCall]:
    """Return the message (row locked) and the call with this id."""
    for message in reversed(await recent_messages(uow, chat)):
        if message.find_call(call_id) is None:
            continue
        locked = await uow.messages.get_for_update(chat.id, message.seq)
        call = locked.find_call(call_id) if locked is not None else None
        if locked is not None and call is not None:
            return locked, call
    raise ToolCallNotFoundError(params={"call_id": call_id})
