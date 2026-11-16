"""Help requests between a student and a mentor, counselor or peer helper (§7)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from app.modules.admission.application.access import AccessPolicy
from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.application.staff import display_name
from app.modules.admission.domain.errors import (
    AdmissionForbiddenError,
    AdmissionNotFoundError,
    CharLimitError,
    InvalidTransitionError,
    SelfClaimError,
)
from app.modules.admission.domain.help_proofs import (
    HelperActivity,
    HelperDirectoryEntry,
    HelpResponse,
    validate_proof_url,
)
from app.modules.admission.domain.permissions import Permission
from app.modules.admission.domain.workflow import (
    HELP_BRIEF_MAX,
    HELP_DEFAULT_DAYS,
    HELP_RESPONSE_MAX,
    HelpKind,
    HelpRequest,
    HelpStatus,
)
from app.modules.admission.ports.unit_of_work import AdmissionUnitOfWork, UowFactory
from app.shared.clock import Clock
from app.shared.contracts.files import FilePurpose, FilesApi
from app.shared.contracts.identity import IdentityDirectory
from app.shared.ids import new_id
from app.shared.notifications import NotificationDraft, NotificationType
from app.shared.rate_limit import RateLimiter

DIRECTORY_MIN_QUERY = 3
DIRECTORY_LIMIT = 10
_DIRECTORY_PER_HOUR = 30
_HOUR = 3600
_OPEN_FOR_RESPONSE: frozenset[HelpStatus] = frozenset({"accepted", "delivered"})
_LIVE_FOR_HELPER: frozenset[HelpStatus] = frozenset(
    {"assigned", "accepted", "delivered"}
)
_RESPONSE_PURPOSES = frozenset({FilePurpose.ADMISSION_DOCUMENT, FilePurpose.AI_UPLOAD})


@dataclass(frozen=True, slots=True)
class HelpDetail:
    """A request with its responses; `activities` only for a helper (reduced)."""

    request: HelpRequest
    responses: list[HelpResponse]
    activities: list[HelperActivity] | None = None
    as_helper: bool = False


def notify_student(
    uow: AdmissionUnitOfWork, student_id: UUID, key: str, payload: dict[str, str]
) -> None:
    """Queue a help-responded notification; payloads carry ids and events only."""
    uow.notify(
        NotificationDraft(
            user_id=student_id,
            type=NotificationType.ADMISSION_HELP_RESPONDED,
            payload=payload,
            dedupe_key=key,
        )
    )


class HelpService:
    """Student side (create, assign, cancel, close) and helper side."""

    def __init__(
        self,
        uow_factory: UowFactory,
        access: AccessPolicy,
        clock: Clock,
        limiter: RateLimiter,
        files: FilesApi | None = None,
        identity: IdentityDirectory | None = None,
    ) -> None:
        """Keep the collaborators."""
        self._uow = uow_factory
        self._access = access
        self._clock = clock
        self._limiter = limiter
        self._files = files
        self._identity = identity

    async def _owner(self, ctx: AdmissionContext) -> None:
        resolution = await self._access.require(
            ctx, ctx.user_id, Permission.ACTIVITIES_READ
        )
        if not resolution.owner:
            raise AdmissionForbiddenError(params={"permission": "help:edit"})

    async def _own_request(
        self, uow: AdmissionUnitOfWork, ctx: AdmissionContext, request_id: UUID
    ) -> HelpRequest:
        request = await uow.help_proofs.get_request(request_id)
        if request is None or request.student_id != ctx.user_id:
            raise AdmissionNotFoundError()
        return request

    async def _helper_request(
        self, uow: AdmissionUnitOfWork, ctx: AdmissionContext, request_id: UUID
    ) -> HelpRequest:
        request = await uow.help_proofs.get_request(request_id)
        if (
            request is None
            or request.helper_user_id != ctx.user_id
            or request.expires_at <= self._clock.now()
        ):
            raise AdmissionNotFoundError()
        return request

    async def _check_file(self, ctx: AdmissionContext, file_id: UUID) -> None:
        """A response file must be the helper's own upload with a known purpose."""
        ref = await self._files.get(file_id) if self._files else None
        if (
            ref is None
            or ref.owner_id != ctx.user_id
            or ref.purpose not in _RESPONSE_PURPOSES
        ):
            raise AdmissionNotFoundError()

    async def create(
        self,
        ctx: AdmissionContext,
        kind: HelpKind,
        brief: str,
        *,
        item_id: UUID | None = None,
        helper_user_id: UUID | None = None,
        expires_in_days: int | None = None,
    ) -> HelpRequest:
        """Create a request, optionally addressed to a helper right away."""
        await self._owner(ctx)
        text = brief.strip()
        if len(text) > HELP_BRIEF_MAX:
            raise CharLimitError(params={"field": "brief", "limit": HELP_BRIEF_MAX})
        days = min(max(expires_in_days or HELP_DEFAULT_DAYS, 1), HELP_DEFAULT_DAYS)
        async with self._uow() as uow:
            if item_id is not None:
                if await uow.help_proofs.item_owner(item_id) != ctx.user_id:
                    raise AdmissionNotFoundError()
            request = await uow.help_proofs.add_request(
                HelpRequest(
                    id=new_id(),
                    student_id=ctx.user_id,
                    kind=kind,
                    brief=text,
                    item_id=item_id,
                    expires_at=self._clock.now() + timedelta(days=days),
                )
            )
            if helper_user_id is not None:
                await self._assign(uow, request, helper_user_id)
            await uow.commit()
        return request

    async def _assign(
        self, uow: AdmissionUnitOfWork, request: HelpRequest, helper_id: UUID
    ) -> None:
        if helper_id == request.student_id:
            raise SelfClaimError()
        if not await uow.help_proofs.helper_opted_in(helper_id):
            raise AdmissionNotFoundError()
        request.move("assigned")
        request.helper_user_id = helper_id
        await uow.help_proofs.save_request(request)
        name = ""
        if self._identity is not None:
            ref = (await self._identity.get_users([request.student_id])).get(
                request.student_id
            )
            name = display_name(ref) if ref else ""
        uow.notify(
            NotificationDraft(
                user_id=helper_id,
                type=NotificationType.ADMISSION_HELP_REQUESTED,
                payload={"request_id": str(request.id), "student_name": name},
                dedupe_key=f"help:{request.id}:assigned:{helper_id}",
            )
        )

    async def assign(
        self, ctx: AdmissionContext, request_id: UUID, helper_user_id: UUID
    ) -> HelpRequest:
        """Address an open or declined request to an opted-in helper."""
        await self._owner(ctx)
        async with self._uow() as uow:
            request = await self._own_request(uow, ctx, request_id)
            await self._assign(uow, request, helper_user_id)
            await uow.commit()
        return request

    async def _student_move(
        self, ctx: AdmissionContext, request_id: UUID, target: HelpStatus
    ) -> HelpRequest:
        await self._owner(ctx)
        async with self._uow() as uow:
            request = await self._own_request(uow, ctx, request_id)
            request.move(target)
            await uow.help_proofs.save_request(request)
            await uow.commit()
        return request

    async def cancel(self, ctx: AdmissionContext, request_id: UUID) -> HelpRequest:
        """Withdraw a request."""
        return await self._student_move(ctx, request_id, "cancelled")

    async def close(self, ctx: AdmissionContext, request_id: UUID) -> HelpRequest:
        """Close a delivered request."""
        return await self._student_move(ctx, request_id, "closed")

    async def _helper_move(
        self, ctx: AdmissionContext, request_id: UUID, target: HelpStatus, event: str
    ) -> HelpRequest:
        async with self._uow() as uow:
            request = await self._helper_request(uow, ctx, request_id)
            request.move(target)
            await uow.help_proofs.save_request(request)
            notify_student(
                uow,
                request.student_id,
                f"help:{request.id}:{event}:{request.lock_version}",
                {"request_id": str(request.id), "event": event},
            )
            await uow.commit()
        return request

    async def accept(self, ctx: AdmissionContext, request_id: UUID) -> HelpRequest:
        """The helper takes the request."""
        return await self._helper_move(ctx, request_id, "accepted", "accepted")

    async def decline(self, ctx: AdmissionContext, request_id: UUID) -> HelpRequest:
        """The helper refuses; the student may pick someone else."""
        return await self._helper_move(ctx, request_id, "declined", "declined")

    async def deliver(self, ctx: AdmissionContext, request_id: UUID) -> HelpRequest:
        """The helper marks the work as delivered."""
        return await self._helper_move(ctx, request_id, "delivered", "delivered")

    async def respond(
        self,
        ctx: AdmissionContext,
        request_id: UUID,
        text: str,
        *,
        url: str | None = None,
        file_id: UUID | None = None,
    ) -> HelpResponse:
        """The helper adds a response to an accepted request."""
        body = text.strip()
        if len(body) > HELP_RESPONSE_MAX:
            raise CharLimitError(params={"field": "text", "limit": HELP_RESPONSE_MAX})
        checked_url = validate_proof_url(url) if url else None
        async with self._uow() as uow:
            request = await self._helper_request(uow, ctx, request_id)
            if request.status not in _OPEN_FOR_RESPONSE:
                raise InvalidTransitionError(
                    params={"status": request.status, "target": "respond"}
                )
            if file_id is not None:
                await self._check_file(ctx, file_id)
            response = await uow.help_proofs.add_response(
                request.id,
                author_user_id=ctx.user_id,
                guest_link_id=None,
                text=body,
                url=checked_url,
                file_id=file_id,
                now=self._clock.now(),
            )
            notify_student(
                uow,
                request.student_id,
                f"help:{request.id}:response:{response.id}",
                {"request_id": str(request.id), "event": "responded"},
            )
            await uow.commit()
        return response

    async def list_own(self, ctx: AdmissionContext) -> list[HelpRequest]:
        """Return the caller's requests."""
        await self._owner(ctx)
        async with self._uow() as uow:
            return await uow.help_proofs.list_requests(ctx.user_id)

    async def list_assigned(self, ctx: AdmissionContext) -> list[HelpRequest]:
        """Return live requests addressed to the caller."""
        async with self._uow() as uow:
            return await uow.help_proofs.list_assigned(ctx.user_id, self._clock.now())

    async def get(self, ctx: AdmissionContext, request_id: UUID) -> HelpDetail:
        """Return a request to its student, or the reduced view to its helper."""
        async with self._uow() as uow:
            request = await uow.help_proofs.get_request(request_id)
            if request is None:
                raise AdmissionNotFoundError()
            responses = await uow.help_proofs.list_responses(request_id)
            if request.student_id == ctx.user_id:
                await self._owner(ctx)
                return HelpDetail(request, responses)
            if (
                request.helper_user_id != ctx.user_id
                or request.status not in _LIVE_FOR_HELPER
                or request.expires_at <= self._clock.now()
            ):
                raise AdmissionNotFoundError()
            activities = await uow.help_proofs.activities_for_helper(request.student_id)
        return HelpDetail(request, responses, activities, as_helper=True)

    async def search_helpers(
        self, ctx: AdmissionContext, query: str
    ) -> list[HelperDirectoryEntry]:
        """Find opted-in helpers by display name (3+ letters, throttled)."""
        await self._owner(ctx)
        text = query.strip()
        if len(text) < DIRECTORY_MIN_QUERY:
            return []
        await self._limiter.hit(
            f"admission:helpers:{ctx.user_id}",
            limit=_DIRECTORY_PER_HOUR,
            window_seconds=_HOUR,
        )
        async with self._uow() as uow:
            return await uow.help_proofs.search_helpers(
                text, exclude=ctx.user_id, limit=DIRECTORY_LIMIT
            )
