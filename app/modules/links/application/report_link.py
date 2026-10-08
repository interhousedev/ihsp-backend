"""Report a public page to the moderation queue (SL-9, UF-PUB-05)."""

from app.modules.links.application.not_found_counter import NotFoundCounter
from app.modules.links.domain.errors import LinkNotFoundError
from app.modules.links.domain.report_reason import ReportReason
from app.modules.links.domain.search_query import extract_slug
from app.modules.links.ports.unit_of_work import UowFactory
from app.shared.clock import Clock
from app.shared.notifications import AuditDraft
from app.shared.rate_limit import RateLimiter

REPORTS_PER_HOUR = 10
WINDOW_SECONDS = 3600
MAX_COMMENT = 500


class ReportLink:
    """Count a report on the link behind a slug; rate limited per IP."""

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        rate_limiter: RateLimiter,
        not_found: NotFoundCounter,
        clock: Clock,
    ) -> None:
        """Initialize the use case."""
        self.uow_factory = uow_factory
        self.rate_limiter = rate_limiter
        self.not_found = not_found
        self.clock = clock

    async def execute(
        self,
        slug: str,
        reason: ReportReason,
        comment: str | None,
        *,
        ip: str | None,
        user_agent: str | None = None,
    ) -> None:
        """Increase the report counter; raise 404 for an unknown slug."""
        await self.rate_limiter.hit(
            f"report:{ip or 'unknown'}",
            limit=REPORTS_PER_HOUR,
            window_seconds=WINDOW_SECONDS,
        )
        async with self.uow_factory() as uow:
            link = await uow.links.get_by_slug(extract_slug(slug))
            if link is None:
                await self.not_found.count(ip)
                raise LinkNotFoundError()
            link.register_report(self.clock.now())
            await uow.links.save(link)
            uow.audit(
                AuditDraft(
                    type="link.reported",
                    ip=ip,
                    user_agent=user_agent,
                    metadata={
                        "link_id": str(link.id),
                        "slug": link.slug,
                        "owner_id": str(link.owner_id),
                        "reason": reason.value,
                        "comment": (comment or "")[:MAX_COMMENT] or None,
                    },
                )
            )
            await uow.commit()
