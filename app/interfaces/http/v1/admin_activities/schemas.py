"""Schemas of the one opportunities catalog (admission and my.iht)."""

import dataclasses
from typing import Any, Literal
from uuid import UUID

from app.interfaces.http.v1.admission.schemas_opportunities import OpportunityFields
from app.modules.activities.ports.gateways import CatalogEntry

from pydantic import BaseModel, Field

Audience = Literal["admission", "my_iht"]


class OpportunityIn(OpportunityFields):
    """Create or overwrite an entry; `lock_version` guards an overwrite."""

    audience: list[Audience] = Field(default_factory=list, max_length=2)
    lock_version: int | None = Field(default=None, ge=0)

    def extra(self) -> dict[str, Any]:
        """Draft fields beyond kind and title, ready for the service."""
        draft = self.draft(None)
        return {
            f.name: getattr(draft, f.name)
            for f in dataclasses.fields(draft)
            if f.name not in ("kind", "title")
        }


class OpportunityOut(OpportunityFields):
    """An entry with its audience and version."""

    id: UUID
    audience: list[Audience]
    archived: bool
    lock_version: int

    @classmethod
    def of(cls, e: CatalogEntry) -> "OpportunityOut":
        """Map a catalog entry."""
        base = OpportunityFields.of_draft(e.draft)
        return cls(
            **base.model_dump(),
            id=e.id,
            audience=sorted(e.audience),
            archived=e.archived,
            lock_version=e.lock_version,
        )


class OpportunityListOut(BaseModel):
    """Entries."""

    items: list[OpportunityOut]


class ArchiveIn(BaseModel):
    """Hide or show an entry."""

    archived: bool = True


class ReviewIn(BaseModel):
    """A club review decision."""

    approve: bool
    reason: str | None = Field(default=None, max_length=1000)


class ReasonIn(BaseModel):
    """A reason."""

    reason: str = Field(min_length=1, max_length=1000)


class ForceTransferIn(BaseModel):
    """The new owner."""

    to_user_id: UUID


class CapabilitiesIn(BaseModel):
    """Club capabilities."""

    capabilities: list[str]


class ClubCountsOut(BaseModel):
    """Clubs by status."""

    active: int
    by_status: dict[str, int]


class ClubAnalyticsOut(BaseModel):
    """Figures of one club for the period."""

    club_id: UUID
    slug: str
    name: Any
    status: str
    members: int
    events: int
    attendance_rate: float | None
    avg_rating: float | None


class AdminClubOut(BaseModel):
    """A club row of the admin list."""

    id: UUID
    slug: str
    name: Any
    status: str
    kind: str
    owner_id: UUID | None
    owner_name: str | None
    member_count: int
    logo_url: str | None = None


class AdminClubListOut(BaseModel):
    """A page of clubs."""

    items: list[AdminClubOut]
    total: int


class AnalyticsOut(BaseModel):
    """Platform-wide club figures for a period."""

    clubs: ClubCountsOut
    events: int
    rsvps: int
    check_ins: int
    per_club: list[ClubAnalyticsOut] = Field(default_factory=list)


class TransferredOut(BaseModel):
    """Ownership was handed over."""

    status: str = "transferred"
