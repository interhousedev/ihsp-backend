"""Redis storage of chat summaries (`ai:summary:{chat_id}`, 30 days)."""

import json
from uuid import UUID

from app.modules.ai.ports.summary_store import StoredSummary

from redis.asyncio import Redis

SUMMARY_TTL_SECONDS = 30 * 24 * 3600


class RedisSummaryStore:
    """Implements SummaryStore."""

    def __init__(self, redis: Redis) -> None:
        """Store the Redis client."""
        self.redis = redis

    async def get(self, chat_id: UUID) -> StoredSummary | None:
        """Return the stored summary."""
        raw = await self.redis.get(f"ai:summary:{chat_id}")
        if raw is None:
            return None
        data = json.loads(raw)
        return StoredSummary(text=data["text"], upto_seq=int(data["upto_seq"]))

    async def put(self, chat_id: UUID, summary: StoredSummary) -> None:
        """Store or replace the summary."""
        payload = json.dumps({"text": summary.text, "upto_seq": summary.upto_seq})
        await self.redis.set(f"ai:summary:{chat_id}", payload, ex=SUMMARY_TTL_SECONDS)
