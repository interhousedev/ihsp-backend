"""SSRF-safe download: transport mechanics shared by the modules that fetch URLs.

The caller supplies a `FetchPolicy` (which schemes, ports and hosts, how redirects
behave, which content types, how big and how long) and two error factories, so each
module keeps its own error types and rules. This file only knows the mechanics: the
name is resolved here, every address must be public, and the connection goes to the
checked address (Host and TLS name stay the host's), so a DNS answer cannot change
between check and use. Every hop, redirects included, is checked again. Redirects
never carry credentials, the body is capped while streaming, and one deadline covers
the whole fetch.

There is no default policy and no "any host" default: a module states its host rule
explicitly (`any_public_host` for "the open web", which still refuses non-public
addresses).
"""

import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urljoin, urlsplit

import httpx

Resolver = Callable[[str], Awaitable[list[str]]]
IpAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
RedirectPolicy = Literal["same_host", "revalidate_any"]
ErrorFactory = Callable[[str], Exception]

_REDIRECTS = frozenset({301, 302, 303, 307, 308})
_DEFAULT_PORTS = {"https": 443, "http": 80}


@dataclass(frozen=True, slots=True)
class FetchPolicy:
    """What a fetch may touch; every field is required so nothing is open by default."""

    schemes: frozenset[str]
    ports: frozenset[int]
    allowed_hosts: Callable[[str], bool]
    redirect_policy: RedirectPolicy
    mime_allow_list: frozenset[str] | None  # None: any content type
    max_bytes: int
    total_timeout: float
    connect_timeout: float
    max_redirects: int = 3
    accept: str = "*/*"


@dataclass(frozen=True, slots=True)
class FetchedBody:
    """A downloaded body and where it finally came from."""

    url: str
    host: str
    path: str  # of the last hop, with its query
    content_type: str
    data: bytes


@dataclass(frozen=True, slots=True)
class CheckedUrl:
    """An allowed URL split into the parts the fetcher needs."""

    scheme: str
    host: str
    port: int
    path: str  # with query


async def system_resolver(host: str) -> list[str]:
    """Resolve a host name to its addresses with the system resolver (OSError)."""
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    return list(dict.fromkeys(str(info[4][0]).split("%", 1)[0] for info in infos))


def is_public(address: str) -> bool:
    """True for a globally routable unicast address (IPv4-mapped IPv6 unwrapped)."""
    try:
        ip: IpAddress = ipaddress.ip_address(address)
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


def any_public_host(host: str) -> bool:
    """Host rule for the open web: a dotted ASCII name, never an IP literal.

    Whether the name resolves to public addresses is checked by the fetcher.
    """
    if not host.isascii() or "." not in host:
        return False
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return True
    return False


def host_or_subdomain_of(domain: str) -> Callable[[str], bool]:
    """Host rule: the domain itself or any subdomain of it."""

    def allowed(host: str) -> bool:
        return host == domain or host.endswith("." + domain)

    return allowed


def check_url(url: str, policy: FetchPolicy, unsafe: ErrorFactory) -> CheckedUrl:
    """Return the parts of an allowed URL, or raise what `unsafe` builds."""
    try:
        parts = urlsplit(url.strip())
        host = (parts.hostname or "").lower()
        port = parts.port
    except ValueError as exc:
        raise unsafe("malformed url") from exc
    scheme = parts.scheme.lower()
    if scheme not in policy.schemes or parts.username or parts.password:
        raise unsafe("scheme not allowed or credentials in url")
    effective = port if port is not None else _DEFAULT_PORTS.get(scheme)
    if effective is None or effective not in policy.ports or not host.isascii():
        raise unsafe("port or host not allowed")
    if not host or not policy.allowed_hosts(host):
        raise unsafe("host not allowed")
    path = parts.path or "/"
    return CheckedUrl(
        scheme, host, effective, path + (f"?{parts.query}" if parts.query else "")
    )


class SafeFetcher:
    """Downloads a URL under a `FetchPolicy`; raises only what the factories build."""

    def __init__(
        self,
        policy: FetchPolicy,
        *,
        unsafe: ErrorFactory,
        failed: ErrorFactory,
        resolver: Resolver = system_resolver,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        """Keep the policy, the error factories, and the replaceable resolver/transport.

        `unsafe(details)` is raised for a URL or address the policy forbids and
        `failed(details)` for a transport or HTTP failure, a timeout or a bad body.
        """
        self._policy = policy
        self._unsafe = unsafe
        self._failed = failed
        self._resolver = resolver
        self._transport = transport

    def check(self, url: str) -> CheckedUrl:
        """Validate a URL against the policy without touching the network."""
        return check_url(url, self._policy, self._unsafe)

    async def fetch(self, url: str) -> FetchedBody:
        """Download the body; every hop is checked again, one deadline for all."""
        try:
            async with asyncio.timeout(self._policy.total_timeout):
                return await self._follow(url)
        except TimeoutError as exc:
            raise self._failed("timeout") from exc

    async def _follow(self, url: str) -> FetchedBody:
        policy = self._policy
        current = url
        origin_host: str | None = None
        for _ in range(policy.max_redirects + 1):
            target = check_url(current, policy, self._unsafe)
            if origin_host is None:
                origin_host = target.host
            elif policy.redirect_policy == "same_host" and target.host != origin_host:
                raise self._unsafe("redirect leaves the host")
            address = await self._public_address(target.host)
            outcome = await self._get_once(target, address)
            if isinstance(outcome, FetchedBody):
                return outcome
            current = urljoin(
                f"{target.scheme}://{target.host}:{target.port}{target.path}", outcome
            )
        raise self._unsafe("too many redirects")

    async def _public_address(self, host: str) -> str:
        try:
            addresses = await self._resolver(host)
        except OSError as exc:
            raise self._failed("dns failed") from exc
        if not addresses or not all(is_public(a) for a in addresses):
            raise self._unsafe("host resolves to a non-public address")
        return addresses[0]

    async def _get_once(self, target: CheckedUrl, address: str) -> FetchedBody | str:
        """Return the body, or the Location of a redirect."""
        policy = self._policy
        ip_host = f"[{address}]" if ":" in address else address
        default = _DEFAULT_PORTS.get(target.scheme)
        host_header = target.host
        if target.port != default:
            host_header = f"{target.host}:{target.port}"
        request = httpx.Request(
            "GET",
            f"{target.scheme}://{ip_host}:{target.port}{target.path}",
            headers={"Host": host_header, "Accept": policy.accept},
            extensions={"sni_hostname": target.host},
        )
        timeout = httpx.Timeout(policy.total_timeout, connect=policy.connect_timeout)
        async with httpx.AsyncClient(
            transport=self._transport, timeout=timeout, follow_redirects=False
        ) as client:
            try:
                response = await client.send(request, stream=True)
            except httpx.HTTPError as exc:
                raise self._failed(f"transport {type(exc).__name__}") from exc
            try:
                return await self._read(response, target)
            finally:
                await response.aclose()

    async def _read(
        self, response: httpx.Response, target: CheckedUrl
    ) -> FetchedBody | str:
        policy = self._policy
        if response.status_code in _REDIRECTS:
            location: str | None = response.headers.get("location")
            if not location:
                raise self._failed("redirect without url")
            return location
        if response.status_code != 200:
            raise self._failed(f"HTTP {response.status_code}")
        content_type = (
            response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        )
        if policy.mime_allow_list is not None and (
            content_type not in policy.mime_allow_list
        ):
            raise self._failed("content type not allowed")
        declared = response.headers.get("content-length", "")
        if declared.isdigit() and int(declared) > policy.max_bytes:
            raise self._failed("file too large")
        data = await self._read_body(response)
        return FetchedBody(
            url=f"{target.scheme}://{target.host}{target.path}",
            host=target.host,
            path=target.path,
            content_type=content_type,
            data=data,
        )

    async def _read_body(self, response: httpx.Response) -> bytes:
        """Stream the body, refusing anything over the policy's size limit."""
        max_bytes = self._policy.max_bytes
        data = bytearray()
        try:
            async for chunk in response.aiter_bytes():
                data.extend(chunk)
                if len(data) > max_bytes:
                    raise self._failed("file too large")
        except httpx.HTTPError as exc:
            raise self._failed(f"transport {type(exc).__name__}") from exc
        return bytes(data)
