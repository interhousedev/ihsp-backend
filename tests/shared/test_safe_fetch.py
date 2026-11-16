"""Policy of the shared SSRF-safe fetcher."""

from collections.abc import Awaitable, Callable
from typing import Any

from app.shared.safe_fetch import (
    FetchPolicy,
    SafeFetcher,
    any_public_host,
    host_or_subdomain_of,
    is_public,
)

import httpx
import pytest


class UnsafeError(Exception):
    """The policy forbids it."""


class FailedError(Exception):
    """Transport failure."""


async def public(host: str) -> list[str]:
    """A public address for every name."""
    return ["93.184.216.34"]


async def private(host: str) -> list[str]:
    """A private address for every name."""
    return ["10.0.0.5"]


def policy(**changes: object) -> FetchPolicy:
    """A strict HTTPS policy."""
    base: dict[str, Any] = {
        "schemes": frozenset({"https"}),
        "ports": frozenset({443}),
        "allowed_hosts": any_public_host,
        "redirect_policy": "same_host",
        "mime_allow_list": frozenset({"text/plain"}),
        "max_bytes": 100,
        "total_timeout": 5.0,
        "connect_timeout": 2.0,
    }
    base.update(changes)
    return FetchPolicy(**base)  # type: ignore[arg-type]


def fetcher(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    resolver: Callable[[str], Awaitable[list[str]]] = public,
    **changes: object,
) -> SafeFetcher:
    """A fetcher over a mock transport."""
    return SafeFetcher(
        policy(**changes),
        unsafe=UnsafeError,
        failed=FailedError,
        resolver=resolver,
        transport=httpx.MockTransport(handler),
    )


def ok(request: httpx.Request) -> httpx.Response:
    """A small text answer."""
    return httpx.Response(200, content=b"hi", headers={"content-type": "text/plain"})


async def test_fetches_a_public_host() -> None:
    """The happy path returns the body."""
    body = await fetcher(ok).fetch("https://example.com/a")
    assert body.data == b"hi"


async def test_private_address_is_refused() -> None:
    """A name that resolves to a private IP is unsafe."""
    with pytest.raises(UnsafeError):
        await fetcher(ok, resolver=private).fetch("https://example.com/a")


@pytest.mark.parametrize(
    "url",
    ["http://example.com/a", "https://example.com:8443/a", "http://example.com:80/"],
)
async def test_scheme_and_port_are_refused(url: str) -> None:
    """Plain HTTP and port 80 (or any other) are not allowed."""
    with pytest.raises(UnsafeError):
        await fetcher(ok).fetch(url)


async def test_redirect_off_host_is_refused_under_same_host() -> None:
    """same_host stops a redirect to another host."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "https://other.example/x"})

    with pytest.raises((UnsafeError, FailedError)):
        await fetcher(handler).fetch("https://example.com/a")


async def test_redirect_to_private_is_refused_when_revalidated() -> None:
    """revalidate_any follows the redirect but checks the new address again."""
    calls: list[str] = []

    async def resolver(host: str) -> list[str]:
        calls.append(host)
        return ["10.0.0.1"] if host == "evil.example" else ["93.184.216.34"]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "https://evil.example/x"})

    with pytest.raises(UnsafeError):
        await fetcher(
            handler, resolver=resolver, redirect_policy="revalidate_any"
        ).fetch("https://example.com/a")
    assert "evil.example" in calls


async def test_mime_not_in_allow_list_is_refused() -> None:
    """Only listed content types pass."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x", headers={"content-type": "image/png"})

    with pytest.raises((UnsafeError, FailedError)):
        await fetcher(handler).fetch("https://example.com/a")


async def test_body_over_cap_is_refused() -> None:
    """The size cap holds."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=b"x" * 500, headers={"content-type": "text/plain"}
        )

    with pytest.raises(FailedError):
        await fetcher(handler).fetch("https://example.com/a")


def test_host_rule_and_address_helpers() -> None:
    """Helpers behave as documented."""
    rule = host_or_subdomain_of("iht.uz")
    assert rule("a.iht.uz") and rule("iht.uz") and not rule("eviliht.uz")
    assert is_public("93.184.216.34") and not is_public("127.0.0.1")
