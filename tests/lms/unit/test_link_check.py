"""Link extraction and the SSRF guard of the link checker."""

from app.modules.lms.domain.authoring.errors import LinkCheckForbiddenTargetError
from app.modules.lms.domain.authoring.link_check import (
    MAX_URLS,
    ensure_safe_url,
    extract_links,
    is_public_address,
)
from app.modules.lms.infrastructure.authoring.http_link_checker import (
    USER_AGENT,
    HttpLinkChecker,
)

import httpx
import pytest

HOSTS = {
    "example.com": ["93.184.216.34"],
    "internal.example.com": ["10.0.0.5"],
    "mixed.example.com": ["93.184.216.34", "127.0.0.1"],
}


async def resolver(host: str, port: int) -> list[str]:
    if host not in HOSTS:
        raise OSError("no such host")
    return HOSTS[host]


def test_extract_dedupes_and_walks_nested_json() -> None:
    draft = {
        "blocks": [
            {"text": "See https://example.com/a, and (https://example.com/b)."},
            {"items": ["http://example.com/a", "https://example.com/a"]},
        ]
    }
    links = extract_links(
        [("s1", "One", draft), ("s2", "Two", {"x": "https://example.com/b"})]
    )
    assert [(link.url, link.step_title) for link in links] == [
        ("https://example.com/a", "One"),
        ("https://example.com/b", "One"),
        ("http://example.com/a", "One"),
    ]


def test_extract_caps_at_200() -> None:
    text = " ".join(f"https://example.com/{i}" for i in range(300))
    assert len(extract_links([("s", "t", {"t": text})])) == MAX_URLS


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.1.1.1",
        "192.168.0.1",
        "169.254.169.254",
        "::1",
        "224.0.0.1",
        "0.0.0.0",
        "fe80::1",
        "::ffff:127.0.0.1",
        "240.0.0.1",
        "not-an-ip",
    ],
)
def test_non_public_addresses_rejected(address: str) -> None:
    assert not is_public_address(address)


def test_public_address_accepted() -> None:
    assert is_public_address("93.184.216.34")


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com/x",
        "file:///etc/passwd",
        "http://127.0.0.1/",
        "http://[::1]/",
        "http://internal.example.com/",
        "http://mixed.example.com/",
        "http://missing.example.com/",
        "http://user:pw@example.com/",
    ],
)
async def test_unsafe_urls_rejected(url: str) -> None:
    with pytest.raises(LinkCheckForbiddenTargetError):
        await ensure_safe_url(url, resolver)


async def test_safe_url_passes() -> None:
    await ensure_safe_url("https://example.com/x", resolver)


def _checker(handler: httpx.MockTransport) -> HttpLinkChecker:
    return HttpLinkChecker(resolver=resolver, transport=handler)


async def test_head_ok_and_headers() -> None:
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200)

    result = await _checker(httpx.MockTransport(handle)).check("https://example.com/")
    assert result.ok and result.status_code == 200
    assert seen[0].method == "HEAD"
    assert seen[0].headers["user-agent"] == USER_AGENT
    assert "origin" not in seen[0].headers and "referer" not in seen[0].headers


async def test_get_fallback_on_405() -> None:
    methods: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        return httpx.Response(405 if request.method == "HEAD" else 200)

    result = await _checker(httpx.MockTransport(handle)).check("https://example.com/")
    assert methods == ["HEAD", "GET"] and result.ok


async def test_redirect_to_private_host_rejected() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "http://internal.example.com/"})

    result = await _checker(httpx.MockTransport(handle)).check("https://example.com/")
    assert not result.ok and result.error == "forbidden-target"


async def test_redirect_chain_limited_to_three() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "https://example.com/next"})

    result = await _checker(httpx.MockTransport(handle)).check("https://example.com/")
    assert result.error == "too-many-redirects"


async def test_followed_redirect_reports_final_status() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/":
            return httpx.Response(301, headers={"location": "/final"})
        return httpx.Response(404)

    result = await _checker(httpx.MockTransport(handle)).check("https://example.com/")
    assert result.status_code == 404 and not result.ok


@pytest.mark.parametrize("address", ["127.0.0.1", "169.254.169.254"])
async def test_host_resolving_to_internal_address_refused(address: str) -> None:
    async def rebinding(host: str, port: int) -> list[str]:
        return [address]

    def handle(request: httpx.Request) -> httpx.Response:
        raise AssertionError("must not connect")

    checker = HttpLinkChecker(resolver=rebinding, transport=httpx.MockTransport(handle))
    result = await checker.check("https://evil.example.com/")
    assert result.error == "forbidden-target"


async def test_connection_pinned_to_validated_address() -> None:
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200)

    await _checker(httpx.MockTransport(handle)).check("https://example.com/x")
    assert seen[0].url.host == "93.184.216.34"
    assert seen[0].headers["host"] == "example.com"
    assert seen[0].extensions["sni_hostname"] == "example.com"
