"""Request and response bodies of the privacy routes."""

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from app.modules.privacy.application.erasure import ErasureEntry
from app.modules.privacy.domain.models import ErasureRequest, ExportJob

from pydantic import BaseModel, Field

ErasureStatusValue = Literal[
    "pending_review", "approved", "rejected", "completed", "cancelled"
]
ExportStatusValue = Literal["queued", "running", "ready", "failed"]
MAX_REASON = 1000


class ExportOut(BaseModel):
    """A data export."""

    id: UUID
    status: ExportStatusValue
    created_at: datetime
    finished_at: datetime | None
    expires_at: datetime | None
    byte_size: int | None

    @classmethod
    def of(cls, job: ExportJob) -> "ExportOut":
        """Map the domain object."""
        return cls(
            id=job.id,
            status=job.status.value,
            created_at=job.created_at,
            finished_at=job.finished_at,
            expires_at=job.expires_at,
            byte_size=job.byte_size,
        )


class ExportListOut(BaseModel):
    """The caller's recent exports, newest first."""

    items: list[ExportOut]


class ExportDownloadOut(BaseModel):
    """A presigned URL valid for 60 seconds."""

    url: str
    expires_in: int = 60


class ErasureRequestOut(BaseModel):
    """An account erasure request."""

    id: UUID
    status: ErasureStatusValue
    requested_at: datetime
    decided_at: datetime | None
    reject_reason: str | None
    closes_on: date | None

    @classmethod
    def of(cls, request: ErasureRequest) -> "ErasureRequestOut":
        """Map the domain object."""
        return cls(
            id=request.id,
            status=request.status.value,
            requested_at=request.requested_at,
            decided_at=request.decided_at,
            reject_reason=request.reject_reason,
            closes_on=request.closes_on,
        )


class MyErasureOut(BaseModel):
    """The caller's open request, if any."""

    request: ErasureRequestOut | None


class AdminErasureOut(ErasureRequestOut):
    """A request in the admin queue, with the requester."""

    user_id: UUID
    name: str | None
    login: str | None
    roles: list[str]

    @classmethod
    def of_entry(cls, entry: ErasureEntry) -> "AdminErasureOut":
        """Map the request with the account details."""
        base = ErasureRequestOut.of(entry.request)
        account = entry.account
        return cls(
            **base.model_dump(),
            user_id=entry.request.user_id,
            name=account.name if account else None,
            login=account.login if account else None,
            roles=sorted(r.value for r in account.roles) if account else [],
        )


class AdminErasureListOut(BaseModel):
    """A page of the admin queue."""

    items: list[AdminErasureOut]


class RejectIn(BaseModel):
    """The reason is shown to the user."""

    reason: str | None = Field(default=None, max_length=MAX_REASON)
