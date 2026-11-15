"""The EMIS client keeps to its time budget and downloads only from EMIS hosts."""

import time
from collections.abc import AsyncIterator, Iterator

from app.modules.identity.application.register_models import EmisRequestError
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
CDN = "https://cdn-emis.edu.uz/f.pdf"


class StuckLimiter(EmisRateLimiter):
    """Never admits a request, like a saturated shared limiter."""

    async def acquire(self, bucket: str, qps: int) -> None:
        import asyncio

        await asyncio.sleep(3600)


@pytest.fixture
def emis_http() -> Iterator[respx.MockRouter]:
    with respx.mock(base_url=BASE, assert_all_called=False) as router:
        yield router


def build(http: httpx.AsyncClient, limiter: type[EmisRateLimiter]) -> EmisClient:
    redis = FakeRedis(server=FakeServer(), decode_responses=True)
    return EmisClient(
        http,
        profile_path=PROFILE,
        limiter=limiter(redis),
        pause=EmisPause(redis),
        max_qps=1000,
        file_max_qps=1000,
    )


@pytest.fixture
async def client(emis_http: respx.MockRouter) -> AsyncIterator[EmisClient]:
    http = httpx.AsyncClient(base_url=BASE)
    yield build(http, EmisRateLimiter)
    await http.aclose()


async def test_the_deadline_covers_waiting_for_the_limiter(
    emis_http: respx.MockRouter,
) -> None:
    """Queueing behind the limiter counts against the budget."""
    http = httpx.AsyncClient(base_url=BASE)
    stuck = build(http, StuckLimiter)

    started = time.monotonic()
    with pytest.raises(EmisRequestError) as caught:
        await stuck.get_json(PROFILE, "tok", deadline=started + 0.2)

    assert caught.value.reason == "timeout"
    assert time.monotonic() - started < 5
    await http.aclose()


async def test_a_foreign_host_is_refused(
    client: EmisClient, emis_http: respx.MockRouter
) -> None:
    route = emis_http.get("https://evil.example.com/f.pdf").respond(200, content=b"x")

    with pytest.raises(EmisRequestError) as caught:
        await client.download("tok", "https://evil.example.com/f.pdf", 100)

    assert caught.value.reason == "bad_material_url"
    assert route.call_count == 0


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/f.pdf",
        "http://169.254.169.254/latest/meta-data",
        "http://10.0.0.5/f.pdf",
        "http://[::1]/f.pdf",
        "https://cdn-emis.edu.uz.evil.example/f.pdf",
    ],
)
async def test_ip_literals_and_lookalike_hosts_are_refused(
    client: EmisClient, url: str
) -> None:
    with pytest.raises(EmisRequestError) as caught:
        await client.download("tok", url, 100)

    assert caught.value.reason == "bad_material_url"


async def test_an_approved_host_and_its_subdomain_download(
    client: EmisClient, emis_http: respx.MockRouter
) -> None:
    emis_http.get(CDN).respond(200, content=b"pdf")
    emis_http.get("https://files.cdn-emis.edu.uz/g.pdf").respond(200, content=b"two")

    first = await client.download("tok", CDN, 100)
    second = await client.download("tok", "https://files.cdn-emis.edu.uz/g.pdf", 100)

    assert (first.data, second.data) == (b"pdf", b"two")


async def test_a_redirect_to_an_approved_host_is_followed_without_the_token(
    client: EmisClient, emis_http: respx.MockRouter
) -> None:
    emis_http.get("https://emis.edu.uz/m.pdf").respond(302, headers={"location": CDN})
    cdn = emis_http.get(CDN).respond(200, content=b"pdf")

    got = await client.download("tok", "https://emis.edu.uz/m.pdf", 100)

    assert got.data == b"pdf"
    assert "authorization" not in cdn.calls.last.request.headers


@pytest.mark.parametrize(
    "target",
    ["https://evil.example.com/x", "http://169.254.169.254/x", "http://[::1]/"],
)
async def test_a_redirect_to_a_forbidden_target_is_refused(
    client: EmisClient, emis_http: respx.MockRouter, target: str
) -> None:
    emis_http.get(CDN).respond(302, headers={"location": target})
    hit = emis_http.get(target).respond(200, content=b"secret")

    with pytest.raises(EmisRequestError) as caught:
        await client.download("tok", CDN, 100)

    assert caught.value.reason == "bad_material_url"
    assert hit.call_count == 0
