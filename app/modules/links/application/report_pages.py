"""HTML report form for short link pages (no JavaScript)."""

from app.modules.links.application.not_found_counter import NotFoundCounter
from app.modules.links.application.public_pages import PublicPages
from app.modules.links.application.report_link import ReportLink
from app.modules.links.application.views import WebResponse
from app.modules.links.domain.errors import LinkNotFoundError
from app.modules.links.domain.locale import pick_locale
from app.modules.links.domain.report_reason import ReportReason
from app.modules.links.ports.unit_of_work import UowFactory
from app.shared.base_error import RateLimitedError


class ReportPages:
    """Show and submit the report form linked from interstitials and room pages."""

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        report_link: ReportLink,
        not_found: NotFoundCounter,
        pages: PublicPages,
    ) -> None:
        """Initialize the use case."""
        self.uow_factory = uow_factory
        self.report_link = report_link
        self.not_found = not_found
        self.pages = pages

    async def show(
        self, slug: str, *, ip: str | None, accept_language: str | None
    ) -> WebResponse:
        """Render the form for an existing link, 404 otherwise."""
        locale = pick_locale(accept_language)
        async with self.uow_factory() as uow:
            link = await uow.links.get_by_slug(slug)
        if link is None:
            return await self._missing(ip, locale)
        return self.pages.report_form(locale, link)

    async def submit(
        self,
        slug: str,
        *,
        reason: str,
        comment: str | None,
        ip: str | None,
        accept_language: str | None,
    ) -> WebResponse:
        """Record the report and answer with the thank-you page."""
        locale = pick_locale(accept_language)
        try:
            await self.report_link.execute(slug, _reason(reason), comment, ip=ip)
        except LinkNotFoundError:
            return self.pages.not_found(locale)
        except RateLimitedError as error:
            return self.pages.rate_limited(locale, error.params.get("retry_after"))
        return self.pages.report_done(locale)

    async def _missing(self, ip: str | None, locale: str) -> WebResponse:
        try:
            await self.not_found.count(ip)
        except RateLimitedError as error:
            return self.pages.rate_limited(locale, error.params.get("retry_after"))
        return self.pages.not_found(locale)


def _reason(value: str) -> ReportReason:
    try:
        return ReportReason(value)
    except ValueError:
        return ReportReason.OTHER
