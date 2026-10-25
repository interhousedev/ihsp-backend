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
from app.modules.notebooks.domain.enums import SourceFailure, SourceKind
from app.modules.notebooks.domain.errors import (
    SourceReadError,
    SourceUnsupportedError,
)
from app.modules.notebooks.domain.source_input import SourceInput, UrlInput
from app.modules.notebooks.domain.youtube import render_transcript, youtube_video_id
from app.modules.notebooks.ports.transcript import (
    NO_TRANSCRIPT_CODES,
    TranscriptError,
    TranscriptProvider,
)
from app.modules.notebooks.ports.web_fetcher import WebFetcher
from app.shared.web_citations import url_blocked

DEFAULT_PORTS = {"http": 80, "https": 443}
# Caption languages in order of preference; any other language is the next choice.
TRANSCRIPT_LANGUAGES = ("uz", "ru", "en")


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
        self,
        fetcher: WebFetcher | None,
        blocked_domains: Sequence[str] = (),
        transcripts: TranscriptProvider | None = None,
    ) -> None:
        """Store the fetcher (None: URLs are not available), blocked domains, captions.

        `transcripts` (None: no captions) reads YouTube links before the page fetch.
        """
        self.fetcher = fetcher
        self.blocked_domains = tuple(blocked_domains)
        self.transcripts = transcripts

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
        """Read a YouTube video's captions, or fetch the page.

        A video without captions (or with them disabled) falls back to the page; if the
        page has no text either, the source fails as `no_transcript`.
        `SourceReadError` from the fetcher passes through.
        """
        url = str(source.ref["url"])
        video_id = youtube_video_id(url)
        if video_id is None or self.transcripts is None:
            return await self.fetch(url)
        try:
            transcript = await self.transcripts.fetch(video_id, TRANSCRIPT_LANGUAGES)
        except TranscriptError as error:
            return await self._page_after_captions(url, error.code)
        text = render_transcript((s.start, s.text) for s in transcript.segments)
        if not text:
            return await self._page_after_captions(
                url, SourceFailure.NO_TRANSCRIPT.value
            )
        return SourceText(text=text)

    async def _page_after_captions(self, url: str, code: str) -> SourceText:
        """The page of a video whose captions could not be read.

        Raises:
            SourceReadError: `no_transcript` when the captions are missing and the page
                has no text either; other fetch failures pass through.
        """
        try:
            return await self.fetch(url)
        except (SourceReadError, SourceUnsupportedError) as error:
            if code in NO_TRANSCRIPT_CODES:
                raise SourceReadError(SourceFailure.NO_TRANSCRIPT.value) from error
            raise

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
