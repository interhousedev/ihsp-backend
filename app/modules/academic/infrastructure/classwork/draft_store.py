"""Redis store of attendance drafts: ``att:draft:{lesson_id}`` (README → Redis keys)."""

import json
from typing import Any
from uuid import UUID

from app.modules.academic.application.classwork.ports.draft_store import (
    AttendanceDraft,
)

from redis.asyncio import Redis


def _key(lesson_id: UUID) -> str:
    return f"att:draft:{lesson_id}"


class RedisAttendanceDraftStore:
    """Implements AttendanceDraftStore on Redis."""

    def __init__(self, redis: Redis) -> None:
        """Store the client (decoded or raw bytes both work)."""
        self.redis = redis

    async def load(self, lesson_id: UUID) -> AttendanceDraft | None:
        """Return the draft or None."""
        raw: Any = await self.redis.get(_key(lesson_id))
        if raw is None:
            return None
        data = json.loads(raw)
        return AttendanceDraft(
            base_version=int(data["base_version"]),
            absent=[UUID(value) for value in data["absent"]],
        )

    async def save(
        self, lesson_id: UUID, draft: AttendanceDraft, ttl_seconds: int
    ) -> None:
        """Store the draft for ``ttl_seconds`` seconds."""
        payload = json.dumps(
            {
                "base_version": draft.base_version,
                "absent": [str(user_id) for user_id in draft.absent],
            }
        )
        await self.redis.set(_key(lesson_id), payload, ex=max(1, ttl_seconds))

    async def delete(self, lesson_id: UUID) -> None:
        """Forget the draft."""
        await self.redis.delete(_key(lesson_id))
