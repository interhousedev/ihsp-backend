"""Schemas of the staff opportunity table (`/v1/admission/staff/opportunities`)."""

import datetime as dt
from uuid import UUID

from app.interfaces.http.v1.admission.schemas_opportunities import (
    Kind,
    OpportunityFields,
)
from app.modules.admission.domain.opportunities import Opportunity

from pydantic import BaseModel, Field


class StaffOpportunityRowOut(BaseModel):
    """One line of the staff table."""

    id: UUID
    kind: Kind
    title: str
    provider: str | None
    url: str | None
    logo_url: str | None
    country: str | None
    registration_deadlines: list[dt.date]
    exam_dates: list[dt.date]
    archived: bool
    updated_at: dt.datetime
    lock_version: int

    @classmethod
    def of(cls, o: Opportunity) -> "StaffOpportunityRowOut":
        """Map an entry."""
        d = o.draft
        return cls(
            id=o.id,
            kind=d.kind,
            title=d.title,
            provider=d.provider,
            url=d.url,
            logo_url=d.logo_url,
            country=d.country,
            registration_deadlines=list(d.registration_deadlines),
            exam_dates=list(d.exam_dates),
            archived=o.archived,
            updated_at=o.updated_at,
            lock_version=o.lock_version,
        )


class StaffOpportunityPageOut(BaseModel):
    """One page of the staff table."""

    items: list[StaffOpportunityRowOut]
    total: int
    page: int
    page_size: int


class StaffOpportunityOut(BaseModel):
    """An entry with every editable field."""

    id: UUID
    fields: OpportunityFields
    archived: bool
    in_use: bool
    lock_version: int
    created_at: dt.datetime
    updated_at: dt.datetime

    @classmethod
    def of(cls, o: Opportunity, in_use: bool) -> "StaffOpportunityOut":
        """Map an entry."""
        return cls(
            id=o.id,
            fields=OpportunityFields.of_draft(o.draft),
            archived=o.archived,
            in_use=in_use,
            lock_version=o.lock_version,
            created_at=o.created_at,
            updated_at=o.updated_at,
        )


class StaffOpportunityIn(BaseModel):
    """Create an entry."""

    fields: OpportunityFields


class StaffOpportunityPutIn(BaseModel):
    """Overwrite an entry; `lock_version` is the one the form was loaded with."""

    fields: OpportunityFields
    lock_version: int = Field(ge=0)


class StaffOpportunityVisibilityIn(BaseModel):
    """Hide (`archived`) or show an entry."""

    archived: bool
