"""The ongoing bot conversation of each user and the tokens of approval buttons.

Redis in production; a dictionary when the container has no Redis (tests).
"""

import secrets
from uuid import UUID

from redis.asyncio import Redis

PREFIX = "ihsp:bot:ai"
CALL_TTL_SECONDS = 7 * 24 * 3600
TOKEN_BYTES = 8  # 16 hex characters fit the 64 bytes of callback data


def _text(value: bytes | str | None) -> str | None:
    if isinstance(value, bytes):
        return value.decode()
    return value


class AssistantStore:
    """Chat per user (no expiry, `/new` resets it) and pending call tokens."""

    def __init__(self, redis: Redis | None) -> None:
        """Use Redis when there is one."""
        self.redis = redis
        self.memory: dict[str, str] = {}

    async def _get(self, key: str) -> str | None:
        if self.redis is None:
            return self.memory.get(key)
        return _text(await self.redis.get(key))

    async def _set(self, key: str, value: str, ttl: int | None = None) -> None:
        if self.redis is None:
            self.memory[key] = value
            return
        await self.redis.set(key, value, ex=ttl)

    async def _delete(self, key: str) -> None:
        if self.redis is None:
            self.memory.pop(key, None)
            return
        await self.redis.delete(key)

    async def chat_of(self, user_id: UUID) -> UUID | None:
        """The user's ongoing chat."""
        found = await self._get(f"{PREFIX}:chat:{user_id}")
        return UUID(found) if found else None

    async def set_chat(self, user_id: UUID, chat_id: UUID) -> None:
        """Make the chat the user's ongoing one."""
        await self._set(f"{PREFIX}:chat:{user_id}", str(chat_id))

    async def forget_chat(self, user_id: UUID) -> None:
        """The next message starts a new chat."""
        await self._delete(f"{PREFIX}:chat:{user_id}")

    async def remember_call(self, user_id: UUID, chat_id: UUID, call_id: str) -> str:
        """Return a random token that stands for the user's pending tool call."""
        token = secrets.token_hex(TOKEN_BYTES)
        value = f"{user_id}|{chat_id}|{call_id}"
        await self._set(f"{PREFIX}:call:{token}", value, CALL_TTL_SECONDS)
        return token

    async def take_call(self, token: str, user_id: UUID) -> tuple[UUID, str] | None:
        """Spend a token of this user: the chat and call (None when unknown/foreign).

        Single use: the token is deleted on the first valid press.
        """
        key = f"{PREFIX}:call:{token}"
        found = await self._get(key)
        if not found or found.count("|") < 2:
            return None
        owner, chat_id, call_id = found.split("|", 2)
        if owner != str(user_id):
            return None
        await self._delete(key)
        return UUID(chat_id), call_id

    async def remember_visual(self, user_id: UUID, chat_id: UUID, seq: int) -> str:
        """Return a random token for the "See visualization" button of an answer."""
        token = secrets.token_hex(TOKEN_BYTES)
        value = f"{user_id}|{chat_id}|{seq}"
        await self._set(f"{PREFIX}:viz:{token}", value, CALL_TTL_SECONDS)
        return token

    async def visual_of(self, token: str, user_id: UUID) -> tuple[UUID, int] | None:
        """The chat and answer seq of this user's token (None when unknown/foreign)."""
        found = await self._get(f"{PREFIX}:viz:{token}")
        if not found or found.count("|") != 2:
            return None
        owner, chat_id, seq = found.split("|")
        if owner != str(user_id):
            return None
        return UUID(chat_id), int(seq)

    async def visual_url(self, token: str) -> str | None:
        """The share URL made by an earlier press of the button."""
        return await self._get(f"{PREFIX}:vizurl:{token}")

    async def set_visual_url(self, token: str, url: str, ttl: int) -> None:
        """Remember the share URL so a second press reuses it."""
        await self._set(f"{PREFIX}:vizurl:{token}", url, max(ttl, 1))
