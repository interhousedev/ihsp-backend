"""Cartridge import results in Redis (``lms:cc-import:{job_id}``) or in memory."""

import json
from typing import Any, Final

from redis.asyncio import Redis

TTL_SECONDS: Final = 24 * 3600


class RedisCartridgeImportResults:
    """Results as JSON strings that expire with the job."""

    def __init__(self, redis: Redis) -> None:
        """Store the client."""
        self.redis = redis

    async def save(self, job_id: str, result: dict[str, Any]) -> None:
        """Store the result for a day."""
        await self.redis.set(
            f"lms:cc-import:{job_id}", json.dumps(result), ex=TTL_SECONDS
        )

    async def get(self, job_id: str) -> dict[str, Any] | None:
        """Return the stored result."""
        raw = await self.redis.get(f"lms:cc-import:{job_id}")
        if not raw:
            return None
        value = json.loads(raw)
        return value if isinstance(value, dict) else None


class MemoryCartridgeImportResults:
    """Results in a dict (tests)."""

    def __init__(self) -> None:
        """Start empty."""
        self.results: dict[str, dict[str, Any]] = {}

    async def save(self, job_id: str, result: dict[str, Any]) -> None:
        """Store the result."""
        self.results[job_id] = result

    async def get(self, job_id: str) -> dict[str, Any] | None:
        """Return the result."""
        return self.results.get(job_id)
