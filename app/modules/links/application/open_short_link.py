"""Open a short link: redirect, interstitial, 404 or 410 (SL-4, SL-6, SL-7, SL-10)."""

from app.modules.links.application.not_found_counter import NotFoundCounter
from app.modules.links.application.public_pages import PublicPages
from app.modules.links.application.views import WebResponse
from app.modules.links.domain.link import SHORT_KINDS, Link, LinkKind, LinkState
from app.modules.links.domain.locale import pick_locale
from app.modules.links.domain.short_id import RESERVED, is_lookup_slug
from app.modules.links.domain.url_policy import UrlPolicy
from app.modules.links.ports.hit_counter import HitCounter
from app.modules.links.ports.unit_of_work import UowFactory
from app.shared.base_error import GoneError, NotFoundError, RateLimitedError
from app.shared.clock import Clock
from app.shared.contracts.files import FilesApi


class OpenShortLink:
    """Answers `GET /s/{slug}` (dev) and `GET /{slug}` on the short link host."""

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        files: FilesApi,
        policy: UrlPolicy,
        hits: HitCounter,
        not_found: NotFoundCounter,
        pages: PublicPages,
        clock: Clock,
    ) -> None:
        """Initialize the use case."""
        self.uow_factory = uow_factory
        self.files = files
        self.policy = policy
        self.hits = hits
        self.not_found = not_found
        self.pages = pages
        self.clock = clock

    async def execute(
        self, slug: str, *, ip: str | None, accept_language: str | None
    ) -> WebResponse:
        """Return the HTTP answer for the slug."""
        locale = pick_locale(accept_language)
        try:
            return await self._open(slug, ip, locale)
        except RateLimitedError as error:
            retry = error.params.get("retry_after")
            return self.pages.rate_limited(locale, retry)

    async def _open(self, slug: str, ip: str | None, locale: str) -> WebResponse:
        if slug in RESERVED:
            return self.pages.not_found(locale)
        if not is_lookup_slug(slug):
            return await self._missing(ip, locale)
        async with self.uow_factory() as uow:
            link = await uow.links.get_by_slug(slug)
        if link is None or link.kind not in SHORT_KINDS:
            return await self._missing(ip, locale)
        return await self._answer(link, locale)

    async def _missing(self, ip: str | None, locale: str) -> WebResponse:
        await self.not_found.count(ip)
        return self.pages.not_found(locale)

    async def _answer(self, link: Link, locale: str) -> WebResponse:
        state = link.state(self.clock.now())
        if state is LinkState.DISABLED:
            return self.pages.disabled(locale)
        if state is LinkState.GONE or link.is_hidden:
            return self.pages.gone(locale)
        if link.kind is LinkKind.FILE:
            return await self._open_file(link, locale)
        return await self._open_url(link, locale)

    async def _open_file(self, link: Link, locale: str) -> WebResponse:
        if link.file_id is None:
            return self.pages.gone(locale)
        try:
            url = await self.files.download_url(link.file_id)
        except (NotFoundError, GoneError):
            return self.pages.gone(locale)
        await self.hits.hit(link.id)
        return WebResponse(status_code=302, location=url)

    async def _open_url(self, link: Link, locale: str) -> WebResponse:
        target = link.target_url or ""
        if self.policy.is_blocked_url(target):
            return self.pages.disabled(locale)
        await self.hits.hit(link.id)
        if self.policy.needs_interstitial(target):
            return self.pages.interstitial(locale, link)
        return WebResponse(status_code=302, location=target)
