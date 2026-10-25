"""In-memory link checker."""

from app.modules.lms.domain.authoring.link_check import LinkResult


class FakeLinkChecker:
    """Answers from a table; unknown URLs are 200. Records the calls."""

    def __init__(self, statuses: dict[str, int] | None = None) -> None:
        """Set the status per URL."""
        self.statuses = statuses or {}
        self.checked: list[str] = []

    async def check(self, url: str) -> LinkResult:
        """Return the configured status."""
        self.checked.append(url)
        status = self.statuses.get(url, 200)
        return LinkResult(url, status, 200 <= status < 400)
