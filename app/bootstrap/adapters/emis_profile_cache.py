"""Cache of EMIS student profiles: an in-process LFU in front of a Redis entry.

Only ``profile`` is cached; every other EMIS read goes straight to the source. An
entry is fresh while ``clock.now() - stored_at < ttl``; the check uses the injected
clock, so Redis's own expiry is only a memory bound. Each lookup logs one
``emis.cache`` event (``hit``, ``source``, ``age_s``, ``ttl_s``). The counters
``hits`` and ``misses`` of one process are the only other exposure.
"""

import dataclasses
import datetime as dt
import json
from datetime import datetime
from typing import Any
from uuid import UUID

from app.shared.clock import Clock
from app.shared.contracts.emis import (
    EmisCertificate,
    EmisClass,
    EmisClassHour,
    EmisCurriculum,
    EmisFile,
    EmisName,
    EmisProfile,
    EmisSource,
    EmisSubject,
    EmisSubjectRatings,
)
from app.shared.lfu_cache import LFUCache

import structlog
from redis.asyncio import Redis

log = structlog.get_logger(__name__)

_KEY = "emis:profile:{user_id}"


def _encode(stored_at: datetime, profile: EmisProfile) -> str:
    return json.dumps(
        {
            "stored_at": stored_at.isoformat(),
            "profile": dataclasses.asdict(profile),
        }
    )


def _decode(raw: str | bytes) -> tuple[datetime, EmisProfile]:
    data: dict[str, Any] = json.loads(raw)
    fields = data["profile"]
    name = fields.get("institution_name")
    fields["institution_name"] = EmisName(**name) if name is not None else None
    return datetime.fromisoformat(data["stored_at"]), EmisProfile(**fields)


class CachedEmisSource:
    """An EmisSource whose ``profile`` reads are cached in memory and in Redis."""

    def __init__(
        self,
        inner: EmisSource,
        *,
        redis: Redis,
        clock: Clock,
        ttl_seconds: int,
        maxsize: int,
    ) -> None:
        """Wrap ``inner``; entries stay fresh for ``ttl_seconds`` on ``clock``."""
        self._inner = inner
        self._redis = redis
        self._clock = clock
        self._ttl = ttl_seconds
        self._memory: LFUCache[UUID, tuple[datetime, EmisProfile]] = LFUCache(
            maxsize=maxsize
        )
        self.hits = 0
        self.misses = 0

    @property
    def memory_size(self) -> int:
        """Number of profiles in the in-process cache."""
        return len(self._memory)

    def in_memory(self, user_id: UUID) -> bool:
        """True when the in-process cache holds the student's profile."""
        return user_id in self._memory

    async def profile(self, user_id: UUID) -> EmisProfile:
        """Return the cached profile, reading EMIS only on a miss."""
        now = self._clock.now()
        entry = self._memory.get(user_id)
        if entry is not None and self._fresh(entry[0], now):
            return self._hit(entry, "memory", now)
        raw = await self._redis.get(_KEY.format(user_id=user_id))
        if raw is not None:
            stored = _decode(raw)
            if self._fresh(stored[0], now):
                self._memory[user_id] = stored
                return self._hit(stored, "redis", now)
        profile = await self._inner.profile(user_id)
        self._memory[user_id] = (now, profile)
        await self._redis.set(
            _KEY.format(user_id=user_id), _encode(now, profile), ex=self._ttl
        )
        self.misses += 1
        log.info("emis.cache", hit=False, source="emis", ttl_s=self._ttl)
        return profile

    def _fresh(self, stored_at: datetime, now: datetime) -> bool:
        return (now - stored_at).total_seconds() < self._ttl

    def _hit(
        self, entry: tuple[datetime, EmisProfile], source: str, now: datetime
    ) -> EmisProfile:
        self.hits += 1
        age = int((now - entry[0]).total_seconds())
        log.info("emis.cache", hit=True, source=source, age_s=age, ttl_s=self._ttl)
        return entry[1]

    async def subjects(self, user_id: UUID) -> list[EmisSubject]:
        """Pass through to EMIS."""
        return await self._inner.subjects(user_id)

    async def curriculum(self, user_id: UUID) -> EmisCurriculum:
        """Pass through to EMIS."""
        return await self._inner.curriculum(user_id)

    async def ratings(
        self, user_id: UUID, emis_subject_id: int, semester: int
    ) -> EmisSubjectRatings:
        """Pass through to EMIS."""
        return await self._inner.ratings(user_id, emis_subject_id, semester)

    async def class_hours(self, user_id: UUID) -> list[EmisClassHour]:
        """Pass through to EMIS."""
        return await self._inner.class_hours(user_id)

    async def timetable(
        self, user_id: UUID, begin: dt.date, end: dt.date
    ) -> list[EmisClass]:
        """Pass through to EMIS."""
        return await self._inner.timetable(user_id, begin, end)

    async def download(self, user_id: UUID, url: str, *, max_bytes: int) -> EmisFile:
        """Pass through to EMIS."""
        return await self._inner.download(user_id, url, max_bytes=max_bytes)

    async def certificates(self, user_id: UUID) -> list[EmisCertificate]:
        """Pass through to EMIS."""
        return await self._inner.certificates(user_id)

    async def rating_book(self, user_id: UUID) -> str:
        """Pass through to EMIS."""
        return await self._inner.rating_book(user_id)
