"""TelegramSender for TELEGRAM__MODE=fake: logs and keeps the last messages in Redis."""

import json
from typing import Any

import structlog
from redis.asyncio import Redis

log = structlog.get_logger(__name__)

OUTBOX_KEY = "fake-telegram:outbox"
COUNTER_KEY = "fake-telegram:message-id"
KEEP_LAST = 500


class FakeTelegramSender:
    """No network: every call is logged and pushed to the Redis list of the outbox.

    End-to-end tests read `fake-telegram:outbox` (newest entry first).
    """

    def __init__(self, redis: Redis) -> None:
        """Store the Redis client."""
        self.redis = redis

    async def _record(self, entry: dict[str, Any]) -> int:
        message_id = int(await self.redis.incr(COUNTER_KEY))
        entry["message_id"] = message_id
        line = json.dumps(entry, ensure_ascii=False)
        await self.redis.lpush(OUTBOX_KEY, line)  # type: ignore[misc]
        await self.redis.ltrim(OUTBOX_KEY, 0, KEEP_LAST - 1)  # type: ignore[misc]
        log.info("fake_telegram", **entry)
        return message_id

    async def send_message(
        self,
        chat_id: int,
        text_html: str,
        buttons: list[list[dict[str, Any]]] | None = None,
    ) -> int:
        """Record a message."""
        return await self._record(
            {
                "kind": "message",
                "chat_id": chat_id,
                "text_html": text_html,
                "buttons": buttons,
            }
        )

    async def send_document(
        self,
        chat_id: int,
        filename: str,
        data: bytes,
        caption_html: str | None = None,
    ) -> int:
        """Record a document (name and size only)."""
        return await self._record(
            {
                "kind": "document",
                "chat_id": chat_id,
                "filename": filename,
                "size": len(data),
                "caption_html": caption_html,
            }
        )

    async def delete_message(self, chat_id: int, message_id: int) -> None:
        """Record a deletion."""
        await self._record(
            {"kind": "delete", "chat_id": chat_id, "deleted_message_id": message_id}
        )
