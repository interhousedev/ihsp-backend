"""ID-16: the cached JWKS of Hydra."""

from app.modules.identity.domain.errors import HydraUnavailableError
from app.modules.identity.infrastructure.hydra.jwks import JwksCache
from tests.fakes.clock import FixedClock

import httpx
import pytest
import respx
from joserfc.jwk import RSAKey

URL = "http://hydra:4444/.well-known/jwks.json"


def jwks_body(*keys: RSAKey) -> dict:  # noqa: ANN401
    """A JWKS document."""
    return {"keys": [key.as_dict(private=False) for key in keys]}


def cache(clock: FixedClock) -> JwksCache:
    """A cache with a 5 minute TTL."""
    return JwksCache(public_url="http://hydra:4444/", ttl_seconds=300, clock=clock)


@respx.mock
async def test_keys_are_fetched_once_and_cached(clock: FixedClock) -> None:
    """jwks_cache_seconds: one request within the TTL."""
    key = RSAKey.generate_key(2048, parameters={"kid": "k1"})
    route = respx.get(URL).mock(return_value=httpx.Response(200, json=jwks_body(key)))
    jwks = cache(clock)

    first = await jwks.key_set()
    second = await jwks.key_set()

    assert route.call_count == 1
    assert first is second and first.get_by_kid("k1")


@respx.mock
async def test_keys_are_refetched_after_the_ttl(clock: FixedClock) -> None:
    """Rotated keys appear after the TTL."""
    old = RSAKey.generate_key(2048, parameters={"kid": "old"})
    new = RSAKey.generate_key(2048, parameters={"kid": "new"})
    route = respx.get(URL).mock(
        side_effect=[
            httpx.Response(200, json=jwks_body(old)),
            httpx.Response(200, json=jwks_body(new)),
        ]
    )
    jwks = cache(clock)
    await jwks.key_set()

    clock.advance(minutes=6)
    refreshed = await jwks.key_set()

    assert route.call_count == 2 and refreshed.get_by_kid("new")


@respx.mock
async def test_forced_refetch_for_an_unknown_kid_is_rate_limited(
    clock: FixedClock,
) -> None:
    """Random key ids must not make us hammer Hydra: once per 30 seconds."""
    key = RSAKey.generate_key(2048, parameters={"kid": "k1"})
    route = respx.get(URL).mock(return_value=httpx.Response(200, json=jwks_body(key)))
    jwks = cache(clock)
    await jwks.key_set()

    await jwks.key_set(force=True)
    assert route.call_count == 1

    clock.advance(seconds=31)
    await jwks.key_set(force=True)
    assert route.call_count == 2


@respx.mock
async def test_unreachable_hydra_is_a_503(clock: FixedClock) -> None:
    """Errors become HydraUnavailableError."""
    respx.get(URL).mock(return_value=httpx.Response(500))

    with pytest.raises(HydraUnavailableError):
        await cache(clock).key_set()
