"""Public URLs of links."""

from app.modules.links.domain.link import Link


class LinkUrls:
    """Builds short, share and report URLs from the configured origins."""

    def __init__(self, short_links: str, share: str) -> None:
        """Store the short link base (`.../s`) and the share app origin."""
        self.short_links = short_links.rstrip("/")
        self.share = share.rstrip("/")

    def short_url(self, slug: str) -> str:
        """Return the short link URL of a slug."""
        return f"{self.short_links}/{slug}"

    def share_url(self, slug: str) -> str:
        """Return the public share page URL of a slug."""
        return f"{self.share}/ai/{slug}"

    def report_url(self, slug: str) -> str:
        """Return the URL of the report page of a short link."""
        return f"{self.short_links}/{slug}/report"

    def url_for(self, link: Link) -> str:
        """Return the URL people open for this link."""
        if link.is_share:
            return self.share_url(link.slug)
        return self.short_url(link.slug)
