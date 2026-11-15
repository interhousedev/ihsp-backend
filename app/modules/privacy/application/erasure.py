"""Erasure requests: record, decide, cancel, list."""

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from app.modules.privacy.domain.errors import (
    ErasureNotPendingError,
    ErasureRequestNotFoundError,
)
from app.modules.privacy.domain.models import ErasureRequest, ErasureStatus
from app.modules.privacy.ports.unit_of_work import PrivacyUnitOfWork, UowFactory
from app.shared.clock import Clock
from app.shared.contracts.privacy import AccountControl, AccountInfo, ErasureTicket
from app.shared.ids import new_id
from app.shared.notifications import AuditDraft, NotificationDraft, NotificationType

from sqlalchemy.exc import IntegrityError


def _notice(
    request: ErasureRequest, kind: str, **payload: str | None
) -> NotificationDraft:
    return NotificationDraft(
        user_id=request.user_id,
        type=NotificationType.PRIVACY_UPDATE,
        payload={"kind": kind, **payload},
        dedupe_key=f"privacy:{request.id}:{kind}",
    )


class ErasureLifecycle:
    """What identity calls (``ErasureGateway``): record, complete, cancel."""

    def __init__(self, *, uow_factory: UowFactory, clock: Clock) -> None:
        """Store the dependencies."""
        self._uow_factory = uow_factory
        self._clock = clock

    async def request(
        self, user_id: UUID, *, ip: str | None, user_agent: str | None
    ) -> ErasureTicket:
        """Record a ``pending_review`` request; an open one is returned as is."""
        async with self._uow_factory() as uow:
            existing = await uow.erasure.get_open(user_id)
            if existing is not None:
                return ErasureTicket(existing.id, existing.status.value)
            request = ErasureRequest(
                id=new_id(),
                user_id=user_id,
                status=ErasureStatus.PENDING_REVIEW,
                requested_at=self._clock.now(),
            )
            await uow.erasure.add(request)
            uow.audit(
                AuditDraft(
                    type="privacy.erasure_requested",
                    user_id=user_id,
                    ip=ip,
                    user_agent=user_agent,
                    metadata={"request_id": str(request.id)},
                )
            )
            try:
                await uow.commit()
            except IntegrityError as exc:
                conflict = exc  # a concurrent request won the partial unique index
            else:
                return ErasureTicket(request.id, request.status.value)
        async with self._uow_factory() as uow:
            winner = await uow.erasure.get_open(user_id)
            if winner is None:
                raise conflict
            return ErasureTicket(winner.id, winner.status.value)

    async def complete(self, user_id: UUID) -> None:
        """The data was removed: close the approved request."""
        async with self._uow_factory() as uow:
            request = await uow.erasure.get_open(user_id)
            if request is None or request.status is not ErasureStatus.APPROVED:
                return
            request.status = ErasureStatus.COMPLETED
            request.completed_at = self._clock.now()
            await uow.erasure.save(request)
            await uow.commit()

    async def restored(self, user_id: UUID) -> None:
        """The user restored the account: close the open request as cancelled."""
        async with self._uow_factory() as uow:
            request = await uow.erasure.get_open(user_id)
            if request is None:
                return
            request.status = ErasureStatus.CANCELLED
            await uow.erasure.save(request)
            await uow.commit()


class GetMyErasure:
    """The caller's open erasure request."""

    def __init__(self, *, uow_factory: UowFactory) -> None:
        """Store the dependencies."""
        self._uow_factory = uow_factory

    async def execute(self, user_id: UUID) -> ErasureRequest | None:
        """Return the open request or None."""
        async with self._uow_factory() as uow:
            return await uow.erasure.get_open(user_id)


class CancelErasure:
    """The user withdraws a request that no one reviewed yet."""

    def __init__(self, *, uow_factory: UowFactory, clock: Clock) -> None:
        """Store the dependencies."""
        self._uow_factory = uow_factory
        self._clock = clock

    async def execute(self, user_id: UUID) -> ErasureRequest:
        """Cancel the caller's ``pending_review`` request.

        Raises:
            ErasureRequestNotFoundError: The caller has no open request.
            ErasureNotPendingError: It was approved already.
        """
        async with self._uow_factory() as uow:
            request = await uow.erasure.get_open(user_id)
            if request is None:
                raise ErasureRequestNotFoundError
            if request.status is not ErasureStatus.PENDING_REVIEW:
                raise ErasureNotPendingError(params={"status": request.status.value})
            request.status = ErasureStatus.CANCELLED
            request.decided_at = self._clock.now()
            await uow.erasure.save(request)
            uow.audit(
                AuditDraft(
                    type="privacy.erasure_cancelled",
                    user_id=user_id,
                    metadata={"request_id": str(request.id)},
                )
            )
            await uow.commit()
            return request


@dataclass(frozen=True, slots=True)
class ErasureEntry:
    """A request with the requester's account details."""

    request: ErasureRequest
    account: AccountInfo | None


class ListErasureRequests:
    """The admin queue."""

    def __init__(self, *, uow_factory: UowFactory, accounts: AccountControl) -> None:
        """Store the dependencies."""
        self._uow_factory = uow_factory
        self._accounts = accounts

    async def execute(
        self, status: ErasureStatus | None, *, limit: int, offset: int
    ) -> Sequence[ErasureEntry]:
        """Requests newest first, with name, login and roles of the requester."""
        async with self._uow_factory() as uow:
            requests = await uow.erasure.list(status, limit=limit, offset=offset)
        people = await self._accounts.describe([r.user_id for r in requests])
        return [ErasureEntry(r, people.get(r.user_id)) for r in requests]


async def _pending(uow: PrivacyUnitOfWork, request_id: UUID) -> ErasureRequest:
    request = await uow.erasure.get(request_id)
    if request is None:
        raise ErasureRequestNotFoundError
    if request.status is not ErasureStatus.PENDING_REVIEW:
        raise ErasureNotPendingError(params={"status": request.status.value})
    return request


class ApproveErasure:
    """An admin approves: the 30-day deletion window starts."""

    def __init__(
        self, *, uow_factory: UowFactory, accounts: AccountControl, clock: Clock
    ) -> None:
        """Store the dependencies."""
        self._uow_factory = uow_factory
        self._accounts = accounts
        self._clock = clock

    async def execute(
        self, request_id: UUID, *, admin_id: UUID, ip: str | None
    ) -> ErasureRequest:
        """Approve a ``pending_review`` request.

        Raises:
            ErasureRequestNotFoundError: No such request.
            ErasureNotPendingError: It was decided already.
        """
        async with self._uow_factory() as uow:
            request = await _pending(uow, request_id)
            request.closes_on = await self._accounts.start_deletion(
                request.user_id, approved_by=admin_id, ip=ip
            )
            request.status = ErasureStatus.APPROVED
            request.decided_at = self._clock.now()
            request.decided_by = admin_id
            await uow.erasure.save(request)
            uow.notify(
                _notice(
                    request, "erasure_approved", closes_on=request.closes_on.isoformat()
                )
            )
            uow.audit(
                AuditDraft(
                    type="privacy.erasure_approved",
                    user_id=request.user_id,
                    actor_id=admin_id,
                    ip=ip,
                    metadata={"request_id": str(request.id)},
                )
            )
            await uow.commit()
            return request


class RejectErasure:
    """An admin rejects the request; the account stays."""

    def __init__(
        self, *, uow_factory: UowFactory, accounts: AccountControl, clock: Clock
    ) -> None:
        """Store the dependencies."""
        self._uow_factory = uow_factory
        self._accounts = accounts
        self._clock = clock

    async def execute(
        self, request_id: UUID, *, admin_id: UUID, reason: str | None, ip: str | None
    ) -> ErasureRequest:
        """Reject a ``pending_review`` request.

        Raises:
            ErasureRequestNotFoundError: No such request.
            ErasureNotPendingError: It was decided already.
        """
        reason = (reason or "").strip() or None
        async with self._uow_factory() as uow:
            request = await _pending(uow, request_id)
            request.status = ErasureStatus.REJECTED
            request.decided_at = self._clock.now()
            request.decided_by = admin_id
            request.reject_reason = reason
            await uow.erasure.save(request)
            uow.notify(_notice(request, "erasure_rejected", reason=reason))
            uow.audit(
                AuditDraft(
                    type="privacy.erasure_rejected",
                    user_id=request.user_id,
                    actor_id=admin_id,
                    ip=ip,
                    metadata={"request_id": str(request.id)},
                )
            )
            await uow.commit()
        await self._accounts.send_notice(
            request.user_id,
            "privacy-mail-erasure-rejected",
            {"reason": reason or ""},
        )
        return request
