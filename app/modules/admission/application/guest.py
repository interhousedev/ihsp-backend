"""Guest links for external helpers (§7): hashed tokens, sessions, reduced view."""

from __future__ import annotations

import builtins
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from app.modules.admission.application.access import AccessPolicy
from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.application.help import notify_student
from app.modules.admission.domain.errors import (
    AdmissionForbiddenError,
    AdmissionNotFoundError,
    CharLimitError,
    GuestLinkLimitError,
    SelfClaimError,
)
from app.modules.admission.domain.help_proofs import (
    GUEST_SESSION_PREFIX,
    GUEST_TOKEN_PREFIX,
    GuestLinkRecord,
    HelperActivity,
    HelpResponse,
    issue_token,
    token_hash,
    validate_proof_url,
)
from app.modules.admission.domain.permissions import Permission
from app.modules.admission.domain.workflow import (
    GUEST_SESSION_HOURS,
    HELP_BRIEF_MAX,
    HELP_RESPONSE_MAX,
    HelpKind,
    HelpRequest,
    HelpStatus,
    guest_link_terms,
)
from app.modules.admission.ports.repositories import AuditEvent
from app.modules.admission.ports.unit_of_work import AdmissionUnitOfWork, UowFactory
from app.shared.clock import Clock
from app.shared.contracts.identity import IdentityDirectory
from app.shared.ids import hash_token, new_id
from app.shared.rate_limit import RateLimiter

_ATTEMPTS_PER_IP = 30
_ATTEMPTS_PER_PREFIX = 10
_RESPONSES_PER_LINK_HOUR = 20
_WINDOW = 600
_HOUR = 3600
_FINISHED: frozenset[HelpStatus] = frozenset(
    {"closed", "cancelled", "expired", "declined"}
)


@dataclass(frozen=True, slots=True)
class CreatedGuestLink:
    """A new link; `token` is shown once."""

    record: GuestLinkRecord
    token: str
    help_request_id: UUID


@dataclass(frozen=True, slots=True)
class GuestSession:
    """A redeemed link: the session token (shown once) and its expiry."""

    token: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class GuestView:
    """Everything a guest sees: a first name, the request, reduced activities."""

    first_name: str | None
    kind: HelpKind
    brief: str
    status: HelpStatus
    scope: tuple[str, ...]
    expires_at: datetime
    activities: list[HelperActivity]
    responses: list[HelpResponse]


class GuestService:
    """Student-side link management and the guest-side session."""

    def __init__(
        self,
        uow_factory: UowFactory,
        access: AccessPolicy,
        clock: Clock,
        limiter: RateLimiter,
        *,
        default_days: int,
        default_sessions: int,
        max_active: int,
        identity: IdentityDirectory | None = None,
    ) -> None:
        """Keep the collaborators and the configured defaults."""
        self._uow = uow_factory
        self._access = access
        self._clock = clock
        self._limiter = limiter
        self._days = default_days
        self._sessions = default_sessions
        self._max_active = max_active
        self._identity = identity

    async def _owner(self, ctx: AdmissionContext) -> None:
        resolution = await self._access.require(
            ctx, ctx.user_id, Permission.ACTIVITIES_READ
        )
        if not resolution.owner:
            raise AdmissionForbiddenError(params={"permission": "guest_links:edit"})

    def _audit(
        self,
        uow: AdmissionUnitOfWork,
        action: str,
        student_id: UUID,
        link: GuestLinkRecord,
        actor_id: UUID | None,
        kind: str = "user",
    ) -> None:
        uow.access.audit(
            AuditEvent(
                action=action,
                actor_id=actor_id,
                student_id=student_id,
                actor_kind=kind,  # type: ignore[arg-type]
                object_type="guest_link",
                object_id=link.link.id,
                meta={"token_prefix": link.link.token_prefix},
            )
        )

    async def create(
        self,
        ctx: AdmissionContext,
        *,
        label: str | None,
        help_request_id: UUID | None = None,
        item_id: UUID | None = None,
        kind: HelpKind = "other",
        brief: str = "",
        expires_in_days: int | None = None,
        max_sessions: int | None = None,
    ) -> CreatedGuestLink:
        """Issue a link; without a request, a general one is created for it."""
        await self._owner(ctx)
        now = self._clock.now()
        expires_at, sessions = guest_link_terms(
            now,
            expires_in_days or self._days,
            max_sessions or self._sessions,
        )
        text = brief.strip()
        if len(text) > HELP_BRIEF_MAX:
            raise CharLimitError(params={"field": "brief", "limit": HELP_BRIEF_MAX})
        issued = issue_token()
        async with self._uow() as uow:
            repo = uow.help_proofs
            if await repo.count_active(ctx.user_id, now) >= self._max_active:
                raise GuestLinkLimitError(params={"max_active": self._max_active})
            if help_request_id is not None:
                request = await repo.get_request(help_request_id)
                if (
                    request is None
                    or request.student_id != ctx.user_id
                    or request.status in _FINISHED
                ):
                    raise AdmissionNotFoundError()
            else:
                if item_id is not None:
                    if await repo.item_owner(item_id) != ctx.user_id:
                        raise AdmissionNotFoundError()
                request = await repo.add_request(
                    HelpRequest(
                        id=new_id(),
                        student_id=ctx.user_id,
                        kind=kind,
                        brief=text,
                        item_id=item_id,
                        expires_at=expires_at,
                    )
                )
            record = await repo.add_link(
                student_id=ctx.user_id,
                help_request_id=request.id,
                scope=("activities:read", "help:respond"),
                token_hash=issued.token_hash,
                token_prefix=issued.prefix,
                label=(label or "").strip() or None,
                expires_at=expires_at,
                max_sessions=sessions,
                rotated_from=None,
                now=now,
            )
            self._audit(uow, "guest_link.created", ctx.user_id, record, ctx.user_id)
            await uow.commit()
        return CreatedGuestLink(record, issued.token, request.id)

    async def list(self, ctx: AdmissionContext) -> builtins.list[GuestLinkRecord]:
        """Return the caller's links."""
        await self._owner(ctx)
        async with self._uow() as uow:
            return await uow.help_proofs.list_links(ctx.user_id)

    async def _own_link(
        self, uow: AdmissionUnitOfWork, ctx: AdmissionContext, link_id: UUID
    ) -> GuestLinkRecord:
        record = await uow.help_proofs.get_link(link_id)
        if record is None or record.link.student_id != ctx.user_id:
            raise AdmissionNotFoundError()
        return record

    async def revoke(self, ctx: AdmissionContext, link_id: UUID) -> None:
        """Revoke a link at once (open sessions stop with it)."""
        await self._owner(ctx)
        async with self._uow() as uow:
            record = await self._own_link(uow, ctx, link_id)
            await uow.help_proofs.revoke(link_id, self._clock.now(), "student")
            self._audit(uow, "guest_link.revoked", ctx.user_id, record, ctx.user_id)
            await uow.commit()

    async def rotate(self, ctx: AdmissionContext, link_id: UUID) -> CreatedGuestLink:
        """Replace a link by a new token with the same terms."""
        await self._owner(ctx)
        now = self._clock.now()
        issued = issue_token()
        async with self._uow() as uow:
            old = await self._own_link(uow, ctx, link_id)
            await uow.help_proofs.revoke(link_id, now, "rotated")
            record = await uow.help_proofs.add_link(
                student_id=ctx.user_id,
                help_request_id=old.link.help_request_id,
                scope=old.link.scope,
                token_hash=issued.token_hash,
                token_prefix=issued.prefix,
                label=old.label,
                expires_at=old.link.expires_at,
                max_sessions=old.link.max_sessions,
                rotated_from=old.link.id,
                now=old.created_at,
            )
            self._audit(uow, "guest_link.rotated", ctx.user_id, record, ctx.user_id)
            await uow.commit()
        return CreatedGuestLink(record, issued.token, old.link.help_request_id)

    async def claim(self, ctx: AdmissionContext, token: str) -> HelpRequest:
        """An account holder takes over a link: the request becomes theirs."""
        now = self._clock.now()
        await self._limiter.hit(
            f"admission:guest:claim:{ctx.user_id}", limit=10, window_seconds=_WINDOW
        )
        async with self._uow() as uow:
            record = await uow.help_proofs.by_hash(token_hash(token))
            if (
                record is None
                or not token.startswith(GUEST_TOKEN_PREFIX)
                or record.link.revoked_at is not None
                or now >= record.link.expires_at
            ):
                raise AdmissionNotFoundError()
            if record.link.student_id == ctx.user_id:
                raise SelfClaimError()
            request = await uow.help_proofs.get_request(record.link.help_request_id)
            if request is None or request.status in _FINISHED:
                raise AdmissionNotFoundError()
            if (
                request.helper_user_id is not None
                and request.helper_user_id != ctx.user_id
            ):
                raise AdmissionNotFoundError()
            if request.status == "open":
                request.move("assigned")
            request.helper_user_id = ctx.user_id
            await uow.help_proofs.save_request(request)
            await uow.help_proofs.claim(record.link.id, ctx.user_id, now)
            await uow.help_proofs.revoke(record.link.id, now, "claimed")
            self._audit(
                uow, "guest_link.claimed", request.student_id, record, ctx.user_id
            )
            notify_student(
                uow,
                request.student_id,
                f"guest:{record.link.id}:claimed",
                {"request_id": str(request.id), "event": "claimed"},
            )
            await uow.commit()
        return request

    async def _throttle(self, ip_hash: str | None, token: str) -> None:
        if ip_hash:
            await self._limiter.hit(
                f"admission:guest:ip:{ip_hash}",
                limit=_ATTEMPTS_PER_IP,
                window_seconds=_WINDOW,
            )
        await self._limiter.hit(
            f"admission:guest:tok:{token[:8]}",
            limit=_ATTEMPTS_PER_PREFIX,
            window_seconds=_WINDOW,
        )

    async def redeem(self, token: str, ip: str | None) -> GuestSession:
        """Open a 2-hour session; any unusable token gives the same 404."""
        ip_hash = hash_token(ip) if ip else None
        await self._throttle(ip_hash, token)
        if not token.startswith(GUEST_TOKEN_PREFIX):
            raise AdmissionNotFoundError()
        now = self._clock.now()
        session = issue_token(GUEST_SESSION_PREFIX)
        expires = now + timedelta(hours=GUEST_SESSION_HOURS)
        async with self._uow() as uow:
            record = await uow.help_proofs.redeem(
                token_hash(token),
                now,
                session_hash=session.token_hash,
                ip_hash=ip_hash,
                session_expires_at=expires,
            )
            if record is None:
                raise AdmissionNotFoundError()
            request = await uow.help_proofs.get_request(record.link.help_request_id)
            if request is None or request.status in _FINISHED:
                raise AdmissionNotFoundError()
            self._audit(
                uow,
                "guest_link.session",
                record.link.student_id,
                record,
                None,
                "guest",
            )
            if record.link.sessions_used == 1:
                notify_student(
                    uow,
                    record.link.student_id,
                    f"guest:{record.link.id}:opened",
                    {"request_id": str(request.id), "event": "guest_opened"},
                )
            await uow.commit()
        return GuestSession(session.token, expires)

    async def _session(
        self, uow: AdmissionUnitOfWork, session_token: str
    ) -> tuple[GuestLinkRecord, HelpRequest]:
        if not session_token.startswith(GUEST_SESSION_PREFIX):
            raise AdmissionNotFoundError()
        record = await uow.help_proofs.link_of_session(
            token_hash(session_token), self._clock.now()
        )
        if record is None:
            raise AdmissionNotFoundError()
        request = await uow.help_proofs.get_request(record.link.help_request_id)
        if (
            request is None
            or request.status in _FINISHED
            or request.expires_at <= self._clock.now()
        ):
            raise AdmissionNotFoundError()
        return record, request

    async def view(self, session_token: str, ip: str | None) -> GuestView:
        """Return the reduced view for a live session."""
        await self._throttle(hash_token(ip) if ip else None, session_token)
        async with self._uow() as uow:
            record, request = await self._session(uow, session_token)
            activities = (
                await uow.help_proofs.activities_for_helper(
                    record.link.student_id, item_id=request.item_id
                )
                if "activities:read" in record.link.scope
                else []
            )
            responses = await uow.help_proofs.list_responses(request.id)
        first = None
        if self._identity is not None:
            user = await self._identity.get_user(record.link.student_id)
            first = user.first_name if user else None
        return GuestView(
            first,
            request.kind,
            request.brief,
            request.status,
            tuple(record.link.scope),
            record.link.expires_at,
            activities,
            [r for r in responses if r.guest_link_id == record.link.id],
        )

    async def respond(
        self, session_token: str, ip: str | None, text: str, url: str | None
    ) -> HelpResponse:
        """Add a response from the guest (text and an optional public https url)."""
        await self._throttle(hash_token(ip) if ip else None, session_token)
        body = text.strip()
        if len(body) > HELP_RESPONSE_MAX:
            raise CharLimitError(params={"field": "text", "limit": HELP_RESPONSE_MAX})
        checked = validate_proof_url(url) if url else None
        async with self._uow() as uow:
            record, request = await self._session(uow, session_token)
            if "help:respond" not in record.link.scope:
                raise AdmissionNotFoundError()
            await self._limiter.hit(
                f"admission:guest:resp:{record.link.id}",
                limit=_RESPONSES_PER_LINK_HOUR,
                window_seconds=_HOUR,
            )
            response = await uow.help_proofs.add_response(
                request.id,
                author_user_id=None,
                guest_link_id=record.link.id,
                text=body,
                url=checked,
                file_id=None,
                now=self._clock.now(),
            )
            self._audit(
                uow,
                "guest_link.responded",
                record.link.student_id,
                record,
                None,
                "guest",
            )
            notify_student(
                uow,
                record.link.student_id,
                f"help:{request.id}:response:{response.id}",
                {"request_id": str(request.id), "event": "responded"},
            )
            await uow.commit()
        return response
