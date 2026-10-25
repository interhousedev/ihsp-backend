"""EMIS allowance and pause: calls a second per bucket, 429 pauses every process."""

from collections.abc import AsyncIterator, Iterator

from app.modules.identity.application.register_models import (
    EmisFileRetryError,
    EmisPausedError,
)
from app.modules.identity.infrastructure.emis.client import EmisClient
from app.modules.identity.infrastructure.emis.rate_limit import EmisRateLimiter
from app.shared.emis_pause import EmisPause

import httpx
import pytest
import respx
from fakeredis import FakeServer
from fakeredis.aioredis import FakeRedis

BASE = "https://emis.test/api/v1/"
PROFILE = "student-profiles/profile/"
CDN_FILE = "https://cdn.test/topic.pdf"


class FakeTime:
    def __init__(self) -> None:
        self.current = 1_000.0
        self.slept: list[float] = []

    def now(self) -> float:
        return self.current

    async def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.current += seconds


@pytest.fixture
def router() -> Iterator[respx.MockRouter]:
    with respx.mock(assert_all_called=False) as mock:
        yield mock


@pytest.fixture
def redis() -> FakeRedis:
    return FakeRedis(server=FakeServer(), decode_responses=True)


@pytest.fixture
async def client(
    router: respx.MockRouter, redis: FakeRedis
) -> AsyncIterator[EmisClient]:
    http = httpx.AsyncClient(base_url=BASE)
    yield EmisClient(
        http,
        profile_path=PROFILE,
        limiter=EmisRateLimiter(redis),
        pause=EmisPause(redis),
        max_qps=1000,
        file_max_qps=1000,
    )
    await http.aclose()


async def test_limiter_waits_for_the_next_second_past_the_limit(
    redis: FakeRedis,
) -> None:
    """Two calls fit in a second; the third waits until the next second begins."""
    clock = FakeTime()
    limiter = EmisRateLimiter(redis, now=clock.now, sleep=clock.sleep)

    for _ in range(3):
        await limiter.acquire("api", 2)

    assert len(clock.slept) == 1
    assert clock.current == 1_001.0


async def test_limiter_buckets_are_independent(redis: FakeRedis) -> None:
    """A full ``api`` second does not hold back a ``file`` download."""
    clock = FakeTime()
    limiter = EmisRateLimiter(redis, now=clock.now, sleep=clock.sleep)
    await limiter.acquire("api", 1)

    await limiter.acquire("file", 1)

    assert clock.slept == []


async def test_pause_keeps_the_longer_of_two_pauses(redis: FakeRedis) -> None:
    """A short pause does not shorten a long one already in force."""
    pause = EmisPause(redis)
    await pause.pause(120)

    await pause.pause(5)

    assert 100 < await pause.remaining() <= 120


async def test_429_pauses_every_call_without_another_http_request(
    client: EmisClient, router: respx.MockRouter
) -> None:
    """429 with Retry-After: this call raises the pause; the next one never sends."""
    route = router.get(BASE + PROFILE).respond(429, headers={"Retry-After": "90"})

    with pytest.raises(EmisPausedError) as first:
        await client.profile("token")
    with pytest.raises(EmisPausedError):
        await client.profile("token")

    assert first.value.retry_after == 90
    assert route.call_count == 1


async def test_failed_material_download_of_a_5xx_stays_pending(
    client: EmisClient, router: respx.MockRouter
) -> None:
    """A CDN 503 three times is ``EmisFileRetryError``: the next sync tries again."""
    route = router.get(CDN_FILE).respond(503)

    with pytest.raises(EmisFileRetryError):
        await client.download("token", CDN_FILE, max_bytes=1000)

    assert route.call_count == 3
