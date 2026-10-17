"""Fetching the text of a web page or PDF for URL sources, safe against SSRF.

Every hop (the first request and each redirect) goes through the same steps: check
the URL, resolve the host once, refuse the hop if any resolved address is not public,
connect to the validated IP address only (the real name goes into the `Host` header
and the TLS server name), and check the peer address of the connection once more.
"""

import asyncio
import codecs
import io
import ipaddress
import re
import socket
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from http.cookiejar import Cookie, CookieJar
from urllib.parse import urljoin, urlsplit, urlunsplit

from app.modules.notebooks.domain.enums import SourceFailure
from app.modules.notebooks.domain.errors import SourceReadError
from app.modules.notebooks.infrastructure.html_text import extract_html
from app.modules.notebooks.ports.web_fetcher import FetchedPage

import httpx
import structlog
from pypdf import PdfReader

log = structlog.get_logger(__name__)

Resolver = Callable[[str], Awaitable[list[str]]]
IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address

USER_AGENT = "IHSP-Notebooks/1.0"
ALLOWED_TYPES = ("text/html", "text/plain", "application/pdf")
ALLOWED_PORTS = (80, 443)
MAX_REDIRECTS = 3
MAX_ADDRESSES = 4  # validated addresses tried one after another when connecting
MAX_URL_LENGTH = 2048
MAX_HOST_LENGTH = 253
CONNECT_TIMEOUT_SECONDS = 5.0
TITLE_LIMIT = 200
PDF_MAX_PAGES = 300
PDF_MAX_CHARS = 2_000_000
REDIRECT_STATUSES = (301, 302, 303, 307, 308)

_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": ", ".join(ALLOWED_TYPES),
    "Accept-Encoding": "identity",
}
_UNSAFE_URL_CHARS = re.compile(r"[\s\x00-\x1f\x7f\\]")
_NUMERIC_LABEL = re.compile(r"[0-9]+|0[xX][0-9a-fA-F]*")
_IPV4_HEX = re.compile(r"0[xX][0-9a-fA-F]*")
_IPV4_OCTAL = re.compile(r"0[0-7]*")
_IPV4_DECIMAL = re.compile(r"[1-9][0-9]*")
_DNS_LABEL = re.compile(r"[a-z0-9_-]{1,63}")
_BLOCKED_SUFFIXES = (
    ".localhost",
    ".local",
    ".localdomain",
    ".internal",
    ".home.arpa",
    ".lan",
    ".intranet",
    ".corp",
    ".home",
)
_CGNAT = ipaddress.ip_network("100.64.0.0/10")
_NAT64 = ipaddress.ip_network("64:ff9b::/96")
_HEADER_CHARSET = re.compile(r"""charset\s*=\s*["']?\s*([\w.:-]+)""", re.IGNORECASE)
_META_CHARSET = re.compile(
    rb"""<meta[^>]{0,1024}?charset\s*=\s*["']?\s*([\w.:-]+)""", re.IGNORECASE
)
_SPACES = re.compile(r"\s+")
_BOMS = (
    (codecs.BOM_UTF32_LE, "utf-32"),
    (codecs.BOM_UTF32_BE, "utf-32"),
    (codecs.BOM_UTF8, "utf-8-sig"),
    (codecs.BOM_UTF16_LE, "utf-16"),
    (codecs.BOM_UTF16_BE, "utf-16"),
)


# - - - Errors - - -


def _forbidden(details: str) -> SourceReadError:
    return SourceReadError(SourceFailure.FORBIDDEN.value, support_details=details)


def _failed(details: str) -> SourceReadError:
    return SourceReadError(SourceFailure.FETCH_FAILED.value, support_details=details)


def _unsupported(details: str) -> SourceReadError:
    return SourceReadError(
        SourceFailure.UNSUPPORTED_TYPE.value, support_details=details
    )


def _too_large(details: str) -> SourceReadError:
    return SourceReadError(SourceFailure.TOO_LARGE.value, support_details=details)


# - - - Addresses - - -


async def system_resolver(host: str) -> list[str]:
    """Resolve a host name to its IP addresses with the system resolver."""
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    return [str(info[4][0]) for info in infos]


def is_public_address(address: str) -> bool:
    """True if the IP address is globally routable.

    Loopback, private, link-local (including the 169.254.169.254 metadata address),
    multicast, reserved, unspecified and CGNAT (100.64.0.0/10) addresses are not
    public. Neither are IPv6 forms that carry such an IPv4 address: IPv4-mapped,
    IPv4-compatible, 6to4, Teredo and NAT64.
    """
    try:
        ip = ipaddress.ip_address(address.strip())
    except ValueError:
        return False
    return _public(ip)


def _public(ip: IPAddress) -> bool:
    if not _plain_public(ip):
        return False
    if isinstance(ip, ipaddress.IPv4Address):
        return ip not in _CGNAT
    if ip.scope_id or ip.is_site_local:
        return False
    return all(_public(inner) for inner in _wrapped_ipv4(ip))


def _plain_public(ip: IPAddress) -> bool:
    special = (
        ip.is_private,
        ip.is_loopback,
        ip.is_link_local,
        ip.is_multicast,
        ip.is_reserved,
        ip.is_unspecified,
    )
    return ip.is_global and not any(special)


def _wrapped_ipv4(ip: ipaddress.IPv6Address) -> list[ipaddress.IPv4Address]:
    """The IPv4 addresses that an IPv6 address stands for."""
    found: list[ipaddress.IPv4Address] = []
    if ip.ipv4_mapped is not None:
        found.append(ip.ipv4_mapped)
    if ip.sixtofour is not None:
        found.append(ip.sixtofour)
    if ip.teredo is not None:
        found.extend(ip.teredo)
    if ip in _NAT64 or int(ip) >> 32 == 0:  # NAT64 and IPv4-compatible
        found.append(ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF))
    return found


def _ipv4_number(part: str) -> int | None:
    """One part of an IPv4 literal: decimal, octal (leading 0) or hex (0x)."""
    if _IPV4_HEX.fullmatch(part):
        return int(part[2:] or "0", 16)
    if _IPV4_OCTAL.fullmatch(part):
        return int(part, 8)
    if _IPV4_DECIMAL.fullmatch(part):
        return int(part)
    return None


def _ipv4_literal(host: str) -> ipaddress.IPv4Address | None:
    """Read `host` as an IPv4 literal in any notation (`127.1`, `0x7f000001`, ...).

    A host whose last label is a number is never a name: when it is not a valid
    address either, the URL is refused.
    """
    parts = host.split(".")
    if not _NUMERIC_LABEL.fullmatch(parts[-1]):
        return None
    numbers: list[int] = []
    for part in parts:
        number = _ipv4_number(part)
        if number is None or len(parts) > 4:
            raise _forbidden("invalid ip address")
        numbers.append(number)
    *head, last = numbers
    if any(n > 255 for n in head) or last >= 256 ** (4 - len(head)):
        raise _forbidden("invalid ip address")
    value = last
    for index, number in enumerate(head):
        value += number << (8 * (3 - index))
    return ipaddress.IPv4Address(value)


def _ipv6_literal(host: str) -> ipaddress.IPv6Address:
    try:
        return ipaddress.IPv6Address(host)
    except ValueError as exc:
        raise _forbidden("invalid ip address") from exc


def _dns_name(host: str) -> str:
    """Check a host name and return it in its ASCII (IDNA) form."""
    try:
        name = host.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise _forbidden("invalid host name") from exc
    labels = name.split(".")
    if len(labels) < 2 or name.endswith(_BLOCKED_SUFFIXES):
        raise _forbidden("internal host name")
    for label in labels:
        if not _DNS_LABEL.fullmatch(label) or label[0] == "-" or label[-1] == "-":
            raise _forbidden("invalid host name")
    return name


# - - - URLs - - -


@dataclass(frozen=True, slots=True)
class _Target:
    """A checked URL: where to connect and what to send."""

    url: str  # without fragment
    scheme: str
    host: str  # ASCII name, or the address when the URL has an IP literal
    port: int | None
    path: str  # path and query
    literal: bool
    addresses: tuple[str, ...] = ()  # validated, in connection order

    @property
    def host_header(self) -> str:
        """The value of the Host header: the real name, without a default port."""
        default = 443 if self.scheme == "https" else 80
        host = f"[{self.host}]" if ":" in self.host else self.host
        return host if self.port in (None, default) else f"{host}:{self.port}"

    def url_for(self, address: str) -> str:
        """The request URL with the validated IP address in place of the name."""
        ip = f"[{address}]" if ":" in address else address
        port = "" if self.port is None else f":{self.port}"
        return f"{self.scheme}://{ip}{port}{self.path}"

    @property
    def extensions(self) -> dict[str, str]:
        """The TLS server name, so the certificate is checked for the real name."""
        if self.scheme == "https" and not self.literal:
            return {"sni_hostname": self.host}
        return {}


def _host_of(hostname: str | None) -> tuple[str, bool]:
    """Return the checked host and whether it is an IP literal."""
    host = (hostname or "").rstrip(".").lower()
    if not host or len(host) > MAX_HOST_LENGTH:
        raise _forbidden("invalid host")
    if ":" in host:
        return str(_ipv6_literal(host)), True
    number = _ipv4_literal(host)
    if number is not None:
        return str(number), True
    return _dns_name(host), False


def _parse_url(raw: str) -> _Target:
    """Check scheme, credentials, port and host; no network access."""
    url = raw.strip()
    if not url or len(url) > MAX_URL_LENGTH or _UNSAFE_URL_CHARS.search(url):
        raise _forbidden("malformed url")
    try:
        parts = urlsplit(url)
        port = parts.port
        hostname = parts.hostname
    except ValueError as exc:
        raise _forbidden("malformed url") from exc
    if parts.scheme not in ("http", "https"):
        raise _forbidden("scheme not allowed")
    if "@" in parts.netloc:
        raise _forbidden("credentials in url")
    if port is not None and port not in ALLOWED_PORTS:
        raise _forbidden("port not allowed")
    host, literal = _host_of(hostname)
    query = f"?{parts.query}" if parts.query else ""
    return _Target(
        url=urlunsplit(parts._replace(fragment="")),
        scheme=parts.scheme,
        host=host,
        port=port,
        path=(parts.path or "/") + query,
        literal=literal,
    )


# - - - Responses - - -


@dataclass(frozen=True, slots=True)
class Download:
    """A complete, accepted response."""

    url: str
    content_type: str
    charset: str | None
    body: bytes


@dataclass(frozen=True, slots=True)
class _Redirect:
    """A redirect response."""

    location: str


class _NoCookies(CookieJar):
    """A cookie jar that keeps nothing, so no cookie is ever sent back."""

    def set_cookie(self, cookie: Cookie) -> None:
        """Drop the cookie."""


def _same_address(peer: str, expected: str) -> bool:
    try:
        left = ipaddress.ip_address(peer.split("%", 1)[0])
        right = ipaddress.ip_address(expected)
    except ValueError:
        return False
    if isinstance(left, ipaddress.IPv6Address) and left.ipv4_mapped is not None:
        left = left.ipv4_mapped
    return left == right


def _check_peer(response: httpx.Response, address: str) -> None:
    """DNS-rebinding defence: the socket must be connected to the validated IP."""
    stream = response.extensions.get("network_stream")
    peer = stream.get_extra_info("server_addr") if stream is not None else None
    if peer and not _same_address(str(peer[0]), address):
        raise _forbidden("connected to an address that was not validated")


def _check_type(
    response: httpx.Response, allowed: tuple[str, ...] = ALLOWED_TYPES
) -> str:
    raw = str(response.headers.get("content-type", ""))
    content_type = raw.split(";", 1)[0].strip().lower()
    if content_type not in allowed:
        raise _unsupported(f"content type {content_type[:60] or 'missing'}")
    return content_type


def _check_length(response: httpx.Response, limit: int) -> None:
    try:
        length = int(str(response.headers.get("content-length", "")))
    except ValueError:
        return
    if length > limit:
        raise _too_large(f"content length {length}")


def _charset_of(response: httpx.Response) -> str | None:
    match = _HEADER_CHARSET.search(str(response.headers.get("content-type", "")))
    return match.group(1) if match else None


def _redirect(response: httpx.Response) -> _Redirect:
    location = str(response.headers.get("location", "")).strip()
    if not location:
        raise _failed("redirect without a location")
    return _Redirect(location)


# - - - Text - - -


def _codec(label: str | None) -> str | None:
    """The Python codec for a charset label, or None if there is no such text codec."""
    if not label:
        return None
    try:
        name = codecs.lookup(label).name
        b"a".decode(name, errors="replace")  # raises for binary codecs (base64, ...)
    except (LookupError, ValueError):
        return None
    return name


def _meta_codec(body: bytes) -> str | None:
    match = _META_CHARSET.search(body[:4096])
    name = _codec(match.group(1).decode("ascii", "replace")) if match else None
    if name is not None and name.startswith(("utf-16", "utf-32")):
        return "utf-8"  # a page that declares UTF-16 in an ASCII tag is UTF-8
    return name


def _bom_codec(body: bytes) -> str | None:
    for bom, name in _BOMS:
        if body.startswith(bom):
            return name
    return None


def _decode(body: bytes, header_charset: str | None, html: bool) -> str:
    """Decode with the BOM, the header charset, `<meta charset>`, else UTF-8."""
    encoding = _bom_codec(body) or _codec(header_charset)
    if encoding is None and html:
        encoding = _meta_codec(body)
    try:
        return body.decode(encoding or "utf-8", errors="replace")
    except UnicodeError:
        return body.decode("utf-8", errors="replace")


decode_body = _decode  # the decoding of pages, for the material scanner


def _page_text(reader: PdfReader, index: int) -> str:
    try:
        return reader.pages[index].extract_text() or ""
    except Exception:  # pypdf raises many types; one bad page must not lose the rest
        return ""


def _pdf_pages(reader: PdfReader) -> tuple[list[str], list[int]]:
    """The text of each page and where it starts in the joined text."""
    texts: list[str] = []
    offsets: list[int] = []
    length = 0
    for index in range(min(len(reader.pages), PDF_MAX_PAGES)):
        offset = length + (1 if texts else 0)  # pages are joined by "\n"
        if offset >= PDF_MAX_CHARS:
            break
        text = _page_text(reader, index)[: PDF_MAX_CHARS - offset]
        texts.append(text)
        offsets.append(offset)
        length = offset + len(text)
    return texts, offsets


def _pdf_title(reader: PdfReader) -> str | None:
    try:
        metadata = reader.metadata
        raw = metadata.title if metadata is not None else None
    except Exception:  # damaged document information
        return None
    return _SPACES.sub(" ", str(raw or "")).strip()[:TITLE_LIMIT] or None


def _extract_pdf(data: bytes) -> tuple[str | None, str, tuple[int, ...]]:
    """Blocking: title, text and page offsets of a PDF (no OCR)."""
    try:
        reader = PdfReader(io.BytesIO(data), strict=False)
        if reader.is_encrypted and not reader.decrypt(""):
            raise _unsupported("encrypted pdf")
        texts, offsets = _pdf_pages(reader)
        title = _pdf_title(reader)
    except SourceReadError:
        raise
    except Exception as exc:  # pypdf raises many types for damaged files
        raise _unsupported("unreadable pdf") from exc
    if not any(text.strip() for text in texts):
        return title, "", ()
    return title, "\n".join(texts), tuple(offsets)


async def _to_page(download: Download) -> FetchedPage:
    kind = download.content_type
    if kind == "application/pdf":
        title, text, pages = await asyncio.to_thread(_extract_pdf, download.body)
        return FetchedPage(download.url, title, text, kind, pages)
    text = _decode(download.body, download.charset, html=kind == "text/html")
    if kind == "text/html":
        extracted = await asyncio.to_thread(extract_html, text)
        return FetchedPage(download.url, extracted.title, extracted.text, kind)
    return FetchedPage(download.url, None, text, kind)


def _host_for_log(url: str) -> str:
    """Only the host goes into logs: never the path, the query or a body."""
    try:
        return (urlsplit(url).hostname or "")[:MAX_HOST_LENGTH]
    except ValueError:
        return ""


# - - - Fetcher - - -


class HttpWebFetcher:
    """Reads public web pages and PDFs; private networks are never contacted."""

    def __init__(
        self,
        resolver: Resolver = system_resolver,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout_seconds: float = 10.0,
        max_bytes: int = 2_000_000,
    ) -> None:
        """Store the DNS resolver, an optional transport (tests) and the limits."""
        self.resolver = resolver
        self.transport = transport
        self.timeout_seconds = timeout_seconds
        self.max_bytes = max_bytes

    async def fetch(self, url: str) -> FetchedPage:
        """Download `url` and return its main text.

        Raises:
            SourceReadError: `forbidden` (blocked URL or address), `fetch_failed`
                (DNS, network, timeout, HTTP error, redirects), `unsupported_type`
                or `too_large`.
        """
        try:
            return await self._fetch(url)
        except SourceReadError as error:
            log.info(
                "notebooks_web_fetch_failed",
                host=_host_for_log(url),
                failure=error.failure,
            )
            raise

    async def _fetch(self, url: str) -> FetchedPage:
        return await _to_page(await self.download_raw(url))

    async def download_raw(
        self,
        url: str,
        *,
        allowed: tuple[str, ...] = ALLOWED_TYPES,
        max_bytes: int | None = None,
        timeout_seconds: float | None = None,
    ) -> Download:
        """The checked bytes of `url` (every hop SSRF-checked), not yet read as text.

        Raises:
            SourceReadError: As `fetch`.
        """
        try:
            async with asyncio.timeout(timeout_seconds or self.timeout_seconds):
                return await self._download(url, allowed, max_bytes or self.max_bytes)
        except (TimeoutError, httpx.TimeoutException) as exc:
            raise _failed("timeout") from exc
        except (httpx.HTTPError, httpx.InvalidURL, OSError) as exc:
            raise _failed(f"request failed: {type(exc).__name__}") from exc

    def _client(self) -> httpx.AsyncClient:
        timeout = httpx.Timeout(
            self.timeout_seconds,
            connect=min(CONNECT_TIMEOUT_SECONDS, self.timeout_seconds),
        )
        return httpx.AsyncClient(
            transport=self.transport,
            headers=_HEADERS,
            timeout=timeout,
            follow_redirects=False,
            trust_env=False,  # no proxy: the peer must be the validated address
            cookies=_NoCookies(),
            limits=httpx.Limits(max_keepalive_connections=0),
        )

    async def _download(
        self, url: str, allowed: tuple[str, ...], max_bytes: int
    ) -> Download:
        async with self._client() as client:
            current = url
            for _ in range(MAX_REDIRECTS + 1):
                target = await self._target(current)
                result = await self._hop(client, target, allowed, max_bytes)
                if isinstance(result, Download):
                    return result
                current = urljoin(target.url, result.location)
        raise _failed("too many redirects")

    async def _target(self, url: str) -> _Target:
        """Check the URL, resolve the host once and validate every address."""
        target = _parse_url(url)
        if target.literal:
            addresses: tuple[str, ...] = (target.host,)
        else:
            addresses = await self._resolve(target.host)
        if not all(is_public_address(address) for address in addresses):
            raise _forbidden(f"{target.host} is not a public address")
        return replace(target, addresses=addresses)

    async def _resolve(self, host: str) -> tuple[str, ...]:
        try:
            resolved = await self.resolver(host)
        except (OSError, UnicodeError) as exc:
            raise _failed("dns lookup failed") from exc
        addresses = tuple(dict.fromkeys(resolved))
        if not addresses:
            raise _failed("dns lookup returned nothing")
        return addresses

    async def _hop(
        self,
        client: httpx.AsyncClient,
        target: _Target,
        allowed: tuple[str, ...],
        max_bytes: int,
    ) -> Download | _Redirect:
        """One request; a validated address that refuses the connection is skipped."""
        failure: httpx.TransportError | None = None
        for address in target.addresses[:MAX_ADDRESSES]:
            try:
                return await self._request(client, target, address, allowed, max_bytes)
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                failure = exc
        raise _failed("connection failed") from failure

    async def _request(
        self,
        client: httpx.AsyncClient,
        target: _Target,
        address: str,
        allowed: tuple[str, ...],
        max_bytes: int,
    ) -> Download | _Redirect:
        async with client.stream(
            "GET",
            target.url_for(address),
            headers={"Host": target.host_header},
            extensions=target.extensions,
        ) as response:
            _check_peer(response, address)
            status = response.status_code
            log.info("notebooks_web_fetch", host=target.host, status=status)
            if status in REDIRECT_STATUSES:
                return _redirect(response)
            if not 200 <= status < 300:
                raise _failed(f"http {status}")
            content_type = _check_type(response, allowed)
            _check_length(response, max_bytes)
            body = await self._read(response, max_bytes)
        return Download(target.url, content_type, _charset_of(response), body)

    async def _read(self, response: httpx.Response, max_bytes: int) -> bytes:
        chunks: list[bytes] = []
        size = 0
        async for chunk in response.aiter_bytes():
            size += len(chunk)
            if size > max_bytes:
                raise _too_large(f"more than {max_bytes} bytes")
            chunks.append(chunk)
        return b"".join(chunks)
