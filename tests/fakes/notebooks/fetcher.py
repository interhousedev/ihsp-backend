"""WebFetcher for the notebooks tests."""

from app.modules.notebooks.domain.errors import SourceReadError
from app.modules.notebooks.ports.web_fetcher import FetchedPage


class FakeWebFetcher:
    """Pages by URL; a URL can be set to fail with a failure code."""

    def __init__(self) -> None:
        """Start empty."""
        self.pages: dict[str, FetchedPage] = {}
        self.failures: dict[str, str] = {}
        self.calls: list[str] = []

    def add_page(
        self,
        url: str,
        text: str,
        *,
        title: str | None = "A page",
        pages: tuple[int, ...] = (),
    ) -> None:
        """Serve a page."""
        content_type = "application/pdf" if pages else "text/html"
        self.pages[url] = FetchedPage(url, title, text, content_type, pages)

    def fail(self, url: str, failure: str) -> None:
        """Make the fetch of a URL raise ``SourceReadError(failure)``."""
        self.failures[url] = failure

    async def fetch(self, url: str) -> FetchedPage:
        """Return the page or raise like the real fetcher."""
        self.calls.append(url)
        if url in self.failures:
            raise SourceReadError(self.failures[url])
        if url not in self.pages:
            raise SourceReadError("fetch_failed")
        return self.pages[url]
