"""Router for my_chat_member updates (block and unblock, BOT-22)."""

from app.interfaces.bot.routers.common.chat_member.handlers.user_blocked_bot import (
    user_blocked_bot,
)
from app.interfaces.bot.routers.common.chat_member.handlers.user_unblocked_bot import (
    user_unblocked_bot,
)

from aiogram import F, Router
from aiogram.filters.chat_member_updated import KICKED, MEMBER, ChatMemberUpdatedFilter


def build_router() -> Router:
    """Build the chat member router."""
    router = Router(name="common.chat_member")
    private = F.chat.type == "private"
    router.my_chat_member.register(
        user_blocked_bot, ChatMemberUpdatedFilter(KICKED), private
    )
    router.my_chat_member.register(
        user_unblocked_bot, ChatMemberUpdatedFilter(MEMBER), private
    )
    return router
