"""Tutor conversations in Redis: one capped list per student and step."""

import json
from datetime import datetime
from typing import Any
from uuid import UUID

from app.modules.lms.ports.lesson_ai import TutorMessage

KEPT_MESSAGES = 60
TTL_SECONDS = 60 * 60 * 24 * 120  # a school term after the last message


class RedisTutorHistory:
    """Implements ``TutorHistory`` with a Redis list."""

    def __init__(self, redis: Any) -> None:
        """Store the Redis client."""
        self.redis = redis

    @staticmethod
    def _key(user_id: UUID, step_id: UUID) -> str:
        return f"lms:tutor:{user_id}:{step_id}"

    async def read(self, user_id: UUID, step_id: UUID) -> list[TutorMessage]:
        """Return the messages, oldest first."""
        raw = await self.redis.lrange(self._key(user_id, step_id), 0, -1)
        items: list[TutorMessage] = []
        for item in raw:
            data = json.loads(item)
            items.append(
                TutorMessage(
                    data["role"], data["text"], datetime.fromisoformat(data["at"])
                )
            )
        return items

    async def append(
        self, user_id: UUID, step_id: UUID, messages: list[TutorMessage]
    ) -> None:
        """Add messages at the end, keep the last `KEPT_MESSAGES`."""
        key = self._key(user_id, step_id)
        await self.redis.rpush(
            key,
            *[
                json.dumps(
                    {"role": m.role, "text": m.text, "at": m.created_at.isoformat()}
                )
                for m in messages
            ],
        )
        await self.redis.ltrim(key, -KEPT_MESSAGES, -1)
        await self.redis.expire(key, TTL_SECONDS)
