"""Title fetcher fake."""


class FakeTitleFetcher:
    """Returns 'Title of <url>' and remembers what it was asked."""

    def __init__(self, title: str | None = None) -> None:
        """Use a fixed title, or build one from the URL."""
        self.fixed = title
        self.urls: list[str] = []

    async def fetch_title(self, url: str) -> str:
        """Return the fixed title or one derived from the URL."""
        self.urls.append(url)
        return self.fixed or f"Title of {url}"
