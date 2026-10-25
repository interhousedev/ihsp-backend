"""Find the IHSP account behind the Telegram user."""

from collections.abc import Awaitable, Callable
from typing import Any

from app.shared.actor import Actor
from app.shared.contracts.identity import IdentityDirectory, UserRef, UserStatus

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from aiogram.types import User as TelegramUser


async def refresh_account(
    directory: IdentityDirectory, user: UserRef, from_user: TelegramUser
) -> None:
    """Clear the blocked mark (BOT-22) and keep the cached username fresh."""
    accounts = await directory.telegram_accounts(user.id)
    account = next((a for a in accounts if a.telegram_user_id == from_user.id), None)
    if account is None:
        return
    if account.blocked:
        await directory.set_telegram_blocked(from_user.id, False)
    if account.username != from_user.username:
        await directory.touch_telegram(
            from_user.id, from_user.username, from_user.first_name
        )


class ActorMiddleware(BaseMiddleware):
    """Adds ``user`` (UserRef or None) and ``actor`` (Actor or None)."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        """Look the Telegram user up; only active linked accounts count."""
        data["user"] = None
        data["actor"] = None
        from_user: TelegramUser | None = data.get("event_from_user")
        if from_user is not None and not from_user.is_bot:
            directory: IdentityDirectory = data["services"].directory
            user = await directory.user_by_telegram(from_user.id)
            if user is not None and user.status == UserStatus.ACTIVE:
                data["user"] = user
                data["actor"] = Actor(user_id=user.id, roles=user.roles)
                await refresh_account(directory, user, from_user)
        return await handler(event, data)
