"""Use case: open a media link (MCP-B5). Every refusal is the same not found.

The link is a bearer capability limited by expiry, rate limits, revocation and logging:
a holder refused while signed in could sign out inside the 5 hours. See SECURITY.md.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Final
from uuid import UUID

from app.modules.lms.application.learning.issue_media_grant import MEDIA_BLOCK_TYPES
from app.modules.lms.application.learning.revision_loading import load_rendered
from app.modules.lms.application.learning.step_context import (
    load_live_step,
    staff_access,
)
from app.modules.lms.application.learning.types import UowFactory
from app.modules.lms.domain.learning.errors import (
    MediaNotAvailableError,
    StepNotFoundError,
)
from app.modules.lms.domain.learning.live import RenderCache
from app.modules.lms.domain.learning.media_grant import (
    MediaGrant,
    MediaTier,
    hash_token,
)
from app.modules.lms.ports.learning.unit_of_work import LearningUnitOfWork
from app.shared.actor import Actor
from app.shared.clock import Clock
from app.shared.contracts.files import FilesApi
from app.shared.contracts.identity import IdentityDirectory, UserStatus
from app.shared.notifications import AuditDraft
from app.shared.rate_limit import RateLimiter

import structlog

log = structlog.get_logger(__name__)

MEDIA_URL_SECONDS: Final = 900
IP_REDEEMS_PER_MINUTE: Final = 30
GRANT_REDEEMS_PER_HOUR: Final = 100
ANON_REDEEM_CEILING: Final = 200

ConnectorCheck = Callable[[UUID], Awaitable[bool]]


@dataclass(frozen=True, slots=True)
class RedeemedMedia:
    """A short presigned address of the media."""

    url: str
    expires_in: int
    title: str
    tier: MediaTier


@dataclass(frozen=True, slots=True)
class _Decision:
    tier: MediaTier
    reason: str
    title: str = ""


class RedeemMediaGrant:
    """Check a token against live state: nothing here is cached between calls."""

    def __init__(
        self,
        uow_factory: UowFactory,
        clock: Clock,
        cache: RenderCache,
        identity: IdentityDirectory,
        files: FilesApi | None,
        rate_limiter: RateLimiter,
    ) -> None:
        """Store collaborators."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.cache = cache
        self.identity = identity
        self.files = files
        self.rate_limiter = rate_limiter
        self._connector_active: ConnectorCheck | None = None

    def bind_connector_check(self, check: ConnectorCheck) -> None:
        """Set how a connector is checked; identity is wired after this module."""
        self._connector_active = check

    async def execute(
        self, token: str, viewer: Actor | None, ip: str | None
    ) -> RedeemedMedia:
        """Return a presigned address or raise MediaNotAvailableError."""
        if ip:
            await self.rate_limiter.hit(
                f"lms:media:ip:{ip}", limit=IP_REDEEMS_PER_MINUTE, window_seconds=60
            )
        now = self.clock.now()
        async with self.uow_factory() as uow:
            grant = await uow.media_grants.get_by_hash(hash_token(token))
            if grant is None:
                log.info("lms.media_unknown_token")
                raise MediaNotAvailableError()
            decision = await self._decide(uow, grant, viewer, now)
            decision = await self._count(uow, grant, decision, now)
            uow.audit(
                AuditDraft(
                    type="lms.media_redeemed",
                    user_id=grant.issued_to,
                    actor_id=viewer.user_id if viewer else None,
                    ip=ip,
                    metadata={
                        "grant_id": str(grant.id),
                        "course_id": str(grant.course_id),
                        "tier": decision.tier,
                        "reason": decision.reason,
                    },
                )
            )
            await uow.commit()
        if decision.tier == "denied" or self.files is None:
            raise MediaNotAvailableError()
        await self.rate_limiter.hit(
            f"lms:media:grant:{grant.id}",
            limit=GRANT_REDEEMS_PER_HOUR,
            window_seconds=3600,
        )
        url = await self.files.download_url(
            grant.file_id, inline=True, ttl_seconds=MEDIA_URL_SECONDS
        )
        return RedeemedMedia(
            url=url,
            expires_in=MEDIA_URL_SECONDS,
            title=decision.title,
            tier=decision.tier,
        )

    async def _count(
        self,
        uow: LearningUnitOfWork,
        grant: MediaGrant,
        decision: _Decision,
        now: datetime,
    ) -> _Decision:
        """Count an allowed redeem; too many anonymous ones close the link for good."""
        if decision.tier == "denied":
            return decision
        if decision.tier == "anon" and grant.redeem_count >= ANON_REDEEM_CEILING:
            await uow.media_grants.revoke(grant.id, now)
            log.warning("lms.media_grant_abuse", grant_id=str(grant.id))
            return _Decision("denied", "anonymous_ceiling")
        await uow.media_grants.add_redeem(grant.id)
        return decision

    async def _decide(
        self,
        uow: LearningUnitOfWork,
        grant: MediaGrant,
        viewer: Actor | None,
        now: datetime,
    ) -> _Decision:
        reason = await self._dead_reason(uow, grant)
        if reason is not None:
            return _Decision("denied", reason)
        title = await self._live_title(uow, grant)
        if title is None:
            return _Decision("denied", "block_gone")
        if viewer is not None:
            enrolled = await uow.enrollments.get(grant.course_id, viewer.user_id)
            staff = await staff_access(uow, viewer, grant.course_id)
            if enrolled is not None or staff.is_staff:
                return _Decision("enrolled", "member", title)
            return _Decision("denied", "signed_in_not_enrolled")
        if now >= grant.expires_at:
            return _Decision("denied", "expired")
        return _Decision("anon", "within_window", title)

    async def _dead_reason(
        self, uow: LearningUnitOfWork, grant: MediaGrant
    ) -> str | None:
        """Why the link no longer works for anyone."""
        if grant.revoked_at is not None:
            return "revoked"
        users = await self.identity.get_users([grant.issued_to])
        issuer = users.get(grant.issued_to)
        if issuer is None or issuer.status is not UserStatus.ACTIVE:
            return "issuer_inactive"
        if await uow.enrollments.get(grant.course_id, grant.issued_to) is None:
            return "issuer_not_enrolled"
        if grant.connector_id is not None:
            if self._connector_active is None:
                # Fail closed: a process that cannot check must not open the link.
                log.error("lms.media_connector_check_unbound", grant_id=str(grant.id))
                return "connector_check_unbound"
            if not await self._connector_active(grant.connector_id):
                return "connector_revoked"
        return None

    async def _live_title(
        self, uow: LearningUnitOfWork, grant: MediaGrant
    ) -> str | None:
        """The title of the step when the file is still in the live open course."""
        try:
            context = await load_live_step(uow, grant.step_id)
        except StepNotFoundError:
            return None
        if (
            context.course.id != grant.course_id
            or not context.course.is_open_for_students
        ):
            return None
        rendered = await load_rendered(uow, self.cache, context.live_step.revision_id)
        present = any(
            block["id"] == grant.block_id
            and block["type"] in MEDIA_BLOCK_TYPES
            and block.get("file_id") == str(grant.file_id)
            for block in rendered.blocks
        )
        return rendered.title if present else None
