"""Port for reading a page title."""

from typing import Protocol


class TitleFetcher(Protocol):
    """Finds the title of a web page."""

    async def fetch_title(self, url: str) -> str:
        """Return the page title, or the host name when it cannot be read."""
        ...
