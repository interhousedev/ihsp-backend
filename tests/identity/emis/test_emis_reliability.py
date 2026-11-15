"""EMIS reliability: retries, re-login, reason codes and redacted logs."""

import asyncio
import json
import time
from collections.abc import AsyncIterator, Iterator

from app.modules.identity.application.register_models import (
    EmisAuthError,
    EmisRequestError,
)
from app.modules.identity.infrastructure.emis.client import EmisClient
from app.modules.identity.infrastructure.emis.rate_limit import EmisRateLimiter
from app.shared.contracts.emis import EmisUnavailable
from app.shared.emis_pause import EmisPause
from app.shared.upstream_log import MAX_BODY_BYTES, log_body, url_path
from tests.identity.emis.test_emis_gateway import registered_user
from tests.identity.emis.world import World

import httpx
import pytest
import respx
from fakeredis import FakeServer
from fakeredis.aioredis import FakeRedis
from structlog.testing import capture_logs

BASE = "https://emis.test/api/v1/"
PROFILE = "student-profiles/profile/"
TOKEN = "secret-emis-token"


@pytest.fixture
def emis_http() -> Iterator[respx.MockRouter]:
    with respx.mock(base_url=BASE, assert_all_called=False) as router:
        yield router


class Sleeps(list[float]):
    """Records the back-off waits instead of sleeping."""

    async def __call__(self, seconds: float) -> None:
        self.append(seconds)


@pytest.fixture
def sleeps() -> Sleeps:
    return Sleeps()


@pytest.fixture
async def client(
    emis_http: respx.MockRouter, sleeps: Sleeps
) -> AsyncIterator[EmisClient]:
    http = httpx.AsyncClient(base_url=BASE)
    redis = FakeRedis(server=FakeServer(), decode_responses=True)
    yield EmisClient(
        http,
        profile_path=PROFILE,
        limiter=EmisRateLimiter(redis),
        pause=EmisPause(redis),
        max_qps=1000,
        file_max_qps=1000,
        sleep=sleeps,
    )
    await http.aclose()


async def test_timeouts_are_retried_twice_then_unavailable_with_reason(
    client: EmisClient, emis_http: respx.MockRouter, sleeps: Sleeps
) -> None:
    """A GET that always times out: 3 attempts, reason ``timeout``."""
    route = emis_http.get(PROFILE).mock(side_effect=httpx.ReadTimeout("slow"))

    with pytest.raises(EmisRequestError) as caught:
        await client.get_json(PROFILE, TOKEN)

    assert route.call_count == 3
    assert len(sleeps) == 2
    assert caught.value.reason == "timeout"
    assert caught.value.error_id


async def test_a_5xx_is_retried_and_then_succeeds(
    client: EmisClient, emis_http: respx.MockRouter
) -> None:
    """503 then 200 is a success."""
    route = emis_http.get(PROFILE).mock(
        side_effect=[
            httpx.Response(503, text="down"),
            httpx.Response(200, json={"result": {"id": 1}}),
        ]
    )

    got = await client.get_json(PROFILE, TOKEN)

    assert route.call_count == 2
    assert got


async def test_a_persistent_5xx_carries_the_upstream_status(
    client: EmisClient, emis_http: respx.MockRouter
) -> None:
    """Three 502s end as ``upstream_5xx`` with status 502."""
    emis_http.get(PROFILE).respond(502, text="bad gateway")

    with pytest.raises(EmisRequestError) as caught:
        await client.get_json(PROFILE, TOKEN)

    assert (caught.value.reason, caught.value.status) == ("upstream_5xx", 502)


async def test_an_html_login_page_means_the_session_expired(
    client: EmisClient, emis_http: respx.MockRouter
) -> None:
    """A 200 HTML page where JSON was expected is an auth error, not a retry."""
    route = emis_http.get(PROFILE).respond(200, html="<html><body>Login</body></html>")

    with pytest.raises(EmisAuthError):
        await client.get_json(PROFILE, TOKEN)

    assert route.call_count == 1


async def test_a_403_with_a_token_is_an_auth_error(
    client: EmisClient, emis_http: respx.MockRouter
) -> None:
    """403 on a token-bearing request triggers the re-login path."""
    emis_http.get(PROFILE).respond(403, json={"detail": "no"})

    with pytest.raises(EmisAuthError):
        await client.get_json(PROFILE, TOKEN)


async def test_a_login_post_is_not_retried(
    client: EmisClient, emis_http: respx.MockRouter
) -> None:
    """Only idempotent GETs are retried."""
    route = emis_http.post("student-profiles/login/").respond(503, text="down")

    with pytest.raises(EmisRequestError):
        await client.login("student01", "hunter2-password")

    assert route.call_count == 1


async def test_failures_are_logged_with_status_and_without_secrets(
    client: EmisClient, emis_http: respx.MockRouter
) -> None:
    """The log has path (no query), status, attempt; no token or password."""
    emis_http.get(PROFILE).respond(
        502, text='{"access_token": "leaky-value", "x": 1} Bearer abc.def.ghi'
    )

    with capture_logs() as logs, pytest.raises(EmisRequestError):
        await client.get_json(PROFILE + "?semester=3", TOKEN)

    failed = [e for e in logs if e["event"] == "emis_request_failed"]
    assert failed
    first = failed[0]
    assert first["status"] == 502
    assert "?" not in str(first["path"])
    assert first["log_level"] == "warning"
    dump = repr(logs)
    for secret in (TOKEN, "leaky-value", "abc.def.ghi"):
        assert secret not in dump


async def test_a_stale_token_is_replaced_once_for_concurrent_calls(
    world: World,
) -> None:
    """Single-flight: two calls with a revoked token log in exactly once."""
    user_id = await registered_user(world)
    ref = world.secret_ref_of(user_id)
    world.emis.revoke(world.store.secrets[ref].access_token)

    await asyncio.gather(world.gateway.profile(user_id), world.gateway.profile(user_id))

    assert world.emis.calls.count("login") == 1


async def test_a_401_logs_in_again_and_succeeds(world: World) -> None:
    """The revoked token is refused, the gateway re-logs in and retries."""
    user_id = await registered_user(world)
    ref = world.secret_ref_of(user_id)
    world.emis.revoke(world.store.secrets[ref].access_token)

    profile = await world.gateway.profile(user_id)

    assert profile.emis_student_id == 78201
    assert world.emis.calls == ["profile", "login", "profile"]


async def test_an_outage_reports_the_reason_code(world: World) -> None:
    """EMIS down: unavailable with ``params.reason`` and support details."""
    user_id = await registered_user(world)
    world.emis.down = True

    with pytest.raises(EmisUnavailable) as caught:
        await world.gateway.profile(user_id)

    assert caught.value.params["reason"] == "upstream_5xx"
    assert caught.value.support_details


def test_redaction_truncation_and_path() -> None:
    """Secrets are hidden at any depth; non-JSON bodies are never logged."""
    nested = b'{"a": [{"b": {"access_token": "T0K", "n": 1, "Password": 5}}]}'
    text = log_body(nested)
    assert "T0K" not in text and '"n": 1' in text and "5}" not in text
    escaped = json.dumps({"x": json.dumps({"refresh": "S3C"})}).encode()
    assert "S3C" not in log_body(escaped)
    pii = json.dumps({"login": 'a"b\\"c', "pinfl": 123456, "ok": 7}).encode()
    assert log_body(pii) == '{"login": "[redacted]", "pinfl": "[redacted]", "ok": 7}'
    assert log_body(b'{"token": "abc') == "<non-json 14 bytes>"
    raw = b"Authorization: Bearer abc.def"
    assert "abc" not in log_body(raw) and "Bearer" not in log_body(raw)
    html = b'<html><input name="csrf" value="CSRF123"></html>'
    assert log_body(html, "text/html") == f"<html {len(html)} bytes>"
    assert "CSRF123" not in log_body(html)
    started = time.monotonic()
    assert log_body(b"a" * 16_384) == "<non-json 16384 bytes>"
    assert time.monotonic() - started < 0.5
    big = json.dumps({"rows": ["x" * 50] * 200}).encode()
    assert len(log_body(big)) <= MAX_BODY_BYTES + 32
    assert url_path("https://emis.test/api/v1/p/?semester=3") == "/api/v1/p/"
