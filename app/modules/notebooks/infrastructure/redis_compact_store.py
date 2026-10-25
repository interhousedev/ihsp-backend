"""Redis storage of chat summaries (`nb:compact:{notebook}:{user}`, 30 days)."""

import json
from uuid import UUID

from app.modules.notebooks.domain.compaction import CompactSummary

from redis.asyncio import Redis

COMPACT_TTL_SECONDS = 30 * 24 * 3600


def _key(notebook_id: UUID, user_id: UUID) -> str:
    return f"nb:compact:{notebook_id}:{user_id}"


class RedisCompactStore:
    """Implements CompactStore."""

    def __init__(self, redis: Redis) -> None:
        """Store the Redis client."""
        self.redis = redis

    async def get(self, notebook_id: UUID, user_id: UUID) -> CompactSummary | None:
        """Return the stored summary (None when missing or unreadable)."""
        raw = await self.redis.get(_key(notebook_id, user_id))
        if raw is None:
            return None
        try:
            data = json.loads(raw)
            return CompactSummary(
                text=str(data["text"]),
                upto_seq=int(data["upto_seq"]),
                upto_id=UUID(str(data["upto_id"])),
            )
        except (ValueError, KeyError, TypeError):
            return None

    async def put(
        self, notebook_id: UUID, user_id: UUID, summary: CompactSummary
    ) -> None:
        """Store or replace the summary."""
        payload = json.dumps(
            {
                "text": summary.text,
                "upto_seq": summary.upto_seq,
                "upto_id": str(summary.upto_id),
            }
        )
        await self.redis.set(
            _key(notebook_id, user_id), payload, ex=COMPACT_TTL_SECONDS
        )
