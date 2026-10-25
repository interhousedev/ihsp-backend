"""Use case: delete the stored web pages past their retention, with their vectors."""

from app.modules.ai.application.web_pages import WebPageIndex


class PurgeWebPages:
    """Run by the daily job `ai.purge_web_pages`."""

    def __init__(self, pages: WebPageIndex) -> None:
        """Keep the page index that holds the rows."""
        self.pages = pages

    async def execute(self) -> int:
        """Delete what expired; returns how many pages were deleted."""
        report = await self.pages.purge()
        return report.pages
