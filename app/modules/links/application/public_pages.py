"""Public HTML answers: 404, 410, disabled, 429, interstitial and report pages."""

from app.modules.links.application.link_urls import LinkUrls
from app.modules.links.application.views import WebResponse
from app.modules.links.domain.link import Link
from app.modules.links.domain.report_reason import ReportReason
from app.modules.links.ports.page_renderer import PageRenderer

DEFAULT_RETRY_AFTER = 60


class PublicPages:
    """Builds the small HTML pages that visitors of public hosts can see."""

    def __init__(self, renderer: PageRenderer, urls: LinkUrls) -> None:
        """Store the renderer and the URL builder."""
        self.renderer = renderer
        self.urls = urls

    def _page(
        self, status: int, template: str, locale: str, **context: object
    ) -> WebResponse:
        html = self.renderer.render(template, locale, context)
        return WebResponse(status_code=status, html=html)

    def not_found(self, locale: str) -> WebResponse:
        """Page for an ID that never existed."""
        return self._page(404, "not_found", locale)

    def gone(self, locale: str) -> WebResponse:
        """Page for a deleted, revoked or expired link."""
        return self._page(410, "gone", locale)

    def disabled(self, locale: str) -> WebResponse:
        """Page for a link disabled by Administration."""
        return self._page(410, "disabled", locale)

    def rate_limited(self, locale: str, retry_after: int | None) -> WebResponse:
        """Page for too many 404s or wrong PINs from one IP."""
        seconds = retry_after or DEFAULT_RETRY_AFTER
        response = self._page(429, "rate_limited", locale, seconds=seconds)
        return WebResponse(429, response.html, retry_after=seconds)

    def interstitial(self, locale: str, link: Link) -> WebResponse:
        """Page that shows the full destination before the visitor continues."""
        return self._page(
            200,
            "interstitial",
            locale,
            destination=link.target_url,
            report_url=self.urls.report_url(link.slug),
        )

    def report_form(self, locale: str, link: Link) -> WebResponse:
        """Report form of a short link."""
        return self._page(
            200,
            "report_form",
            locale,
            action=self.urls.report_url(link.slug),
            reasons=[reason.value for reason in ReportReason],
        )

    def report_done(self, locale: str) -> WebResponse:
        """Thank-you page after a report."""
        return self._page(202, "report_done", locale)
