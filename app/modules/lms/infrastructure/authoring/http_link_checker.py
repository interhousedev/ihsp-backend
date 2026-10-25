"""Link checker on httpx with an SSRF guard and manual redirects."""

import asyncio
import socket
from urllib.parse import urljoin, urlsplit

from app.modules.lms.domain.authoring.errors import LinkCheckForbiddenTargetError
from app.modules.lms.domain.authoring.link_check import (
    MAX_REDIRECTS,
    LinkResult,
    Resolver,
    ensure_safe_url,
)

import httpx

USER_AGENT = "IHT-LMS-LinkCheck/1.0"
TIMEOUT_SECONDS = 5.0
_REDIRECTS = frozenset({301, 302, 303, 307, 308})


async def system_resolver(host: str, port: int) -> list[str]:
    """Resolve a host to all its addresses through the system resolver."""
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return [str(info[4][0]) for info in infos]


class HttpLinkChecker:
    """HEAD (then GET without reading the body) with every hop re-validated."""

    def __init__(
        self,
        resolver: Resolver = system_resolver,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        """Store the resolver; ``transport`` lets tests avoid the network."""
        self.resolver = resolver
        self.transport = transport

    async def check(self, url: str) -> LinkResult:
        """Follow at most three redirects by hand and report the final status."""
        current = url
        try:
            async with httpx.AsyncClient(
                follow_redirects=False,
                timeout=httpx.Timeout(TIMEOUT_SECONDS),
                headers={"User-Agent": USER_AGENT},
                transport=self.transport,
            ) as client:
                for _ in range(MAX_REDIRECTS + 1):
                    address = await ensure_safe_url(current, self.resolver)
                    status, location = await self._probe(client, current, address)
                    if status in _REDIRECTS and location:
                        current = urljoin(current, location)
                        continue
                    return LinkResult(url, status, 200 <= status < 400)
        except LinkCheckForbiddenTargetError:
            return LinkResult(url, None, False, "forbidden-target")
        except httpx.TimeoutException:
            return LinkResult(url, None, False, "timeout")
        except httpx.HTTPError:
            return LinkResult(url, None, False, "unreachable")
        return LinkResult(url, None, False, "too-many-redirects")

    async def _probe(
        self, client: httpx.AsyncClient, url: str, address: str
    ) -> tuple[int, str | None]:
        """HEAD first; GET (stream, body unread) when HEAD is not supported.

        The connection goes to the validated ``address`` (DNS-rebinding defence)
        with the original Host header and TLS server name.
        """
        response = await self._send(client, "HEAD", url, address)
        if response.status_code in (405, 501):
            response = await self._send(client, "GET", url, address)
        return response.status_code, response.headers.get("location")

    async def _send(
        self, client: httpx.AsyncClient, method: str, url: str, address: str
    ) -> httpx.Response:
        parts = urlsplit(url)
        host = parts.hostname or ""
        ip_host = f"[{address}]" if ":" in address else address
        netloc = f"{ip_host}:{parts.port}" if parts.port else ip_host
        pinned = parts._replace(netloc=netloc).geturl()
        authority = f"{host}:{parts.port}" if parts.port else host
        request = client.build_request(
            method,
            pinned,
            headers={"Host": authority},
            extensions={"sni_hostname": host},
        )
        response = await client.send(request, stream=True)
        await response.aclose()
        return response
