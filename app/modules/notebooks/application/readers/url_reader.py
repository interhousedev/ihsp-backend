"""Source kind `url`: the main text of a web page or PDF (phase 2, § 3.2.1)."""

from collections.abc import Sequence
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID

from app.modules.notebooks.application.readers.base import (
    ResolvedSource,
    SourceText,
    clean_title,
    expect_input,
)
from app.modules.notebooks.domain.entities import Source
from app.modules.notebooks.domain.enums import SourceKind
from app.modules.notebooks.domain.errors import SourceUnsupportedError
from app.modules.notebooks.domain.source_input import SourceInput, UrlInput
from app.modules.notebooks.ports.web_fetcher import WebFetcher
from app.shared.web_citations import url_blocked

DEFAULT_PORTS = {"http": 80, "https": 443}


def normalise_url(raw: str) -> str:
    """Lower-case scheme and host, no fragment, no default port, path at least ``/``.

    Raises:
        SourceUnsupportedError: Not an http(s) URL with a host, or with credentials.
    """
    try:
        parts = urlsplit(raw.strip())
        host = parts.hostname
        port = parts.port
    except ValueError as exc:
        raise SourceUnsupportedError(params={"hint": "url"}) from exc
    scheme = parts.scheme.lower()
    if scheme not in DEFAULT_PORTS:
        raise SourceUnsupportedError(params={"hint": "scheme"})
    if not host or "@" in parts.netloc:
        raise SourceUnsupportedError(params={"hint": "url"})
    name = f"[{host}]" if ":" in host else host
    netloc = name if port in (None, DEFAULT_PORTS[scheme]) else f"{name}:{port}"
    return urlunsplit((scheme, netloc, parts.path or "/", parts.query, ""))


def host_of(url: str) -> str:
    """The host of a normalised URL (the title of a new URL source)."""
    return urlsplit(url).hostname or url


class UrlReader:
    """Fetches pages through the SSRF-safe `WebFetcher`."""

    def __init__(
        self, fetcher: WebFetcher | None, blocked_domains: Sequence[str] = ()
    ) -> None:
        """Store the fetcher (None: URLs are not available) and the blocked domains."""
        self.fetcher = fetcher
        self.blocked_domains = tuple(blocked_domains)

    async def resolve(self, user_id: UUID, source_input: SourceInput) -> ResolvedSource:
        """Any http(s) URL; the fetcher decides at process time whether it is safe."""
        item = expect_input(source_input, UrlInput)
        self.require_fetcher()
        url = normalise_url(item.url)
        if url_blocked(url, self.blocked_domains):
            raise SourceUnsupportedError(params={"hint": "blocked"})
        return ResolvedSource(
            kind=SourceKind.URL,
            title=clean_title(item.title or host_of(url), "Web page"),
            ref={"url": url},
            ref_key=f"url:{url}",
        )

    async def read(self, source: Source) -> SourceText:
        """Fetch the page; `SourceReadError` from the fetcher passes through."""
        return await self.fetch(str(source.ref["url"]))

    async def fetch(self, url: str) -> SourceText:
        """Fetch a URL (also used for URL-based lesson materials)."""
        fetcher = self.require_fetcher()
        page = await fetcher.fetch(url)
        return SourceText(text=page.text, page_starts=tuple(page.pages))

    def require_fetcher(self) -> WebFetcher:
        """Return the fetcher or say that URLs are not available.

        Raises:
            SourceUnsupportedError: No fetcher is configured (hint: paste the text).
        """
        if self.fetcher is None:
            raise SourceUnsupportedError(params={"hint": "paste_text"})
        return self.fetcher
