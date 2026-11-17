"""Schemas of organizations (`/v1/admission/orgs`)."""

import datetime as dt
from typing import Literal
from uuid import UUID

from app.modules.admission.domain.orgs import Organization

from pydantic import BaseModel, Field

OrgKindName = Literal["university", "company", "foundation", "government", "ngo"]


class OrgIn(BaseModel):
    """Create an organization."""

    name: str = Field(min_length=1, max_length=200)
    kind: OrgKindName
    logo_url: str | None = Field(default=None, max_length=2000)
    logo_zoom: float = Field(default=1.0, ge=0.5, le=3.0)
    website: str | None = Field(default=None, max_length=2000)
    country: str | None = Field(default=None, max_length=100)


class OrgPatch(BaseModel):
    """Change the given fields of an organization."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    kind: OrgKindName | None = None
    logo_url: str | None = Field(default=None, max_length=2000)
    logo_zoom: float | None = Field(default=None, ge=0.5, le=3.0)
    website: str | None = Field(default=None, max_length=2000)
    country: str | None = Field(default=None, max_length=100)


class OrgOut(BaseModel):
    """An organization."""

    id: UUID
    name: str
    kind: OrgKindName
    logo_url: str | None
    logo_zoom: float
    website: str | None
    country: str | None
    updated_at: dt.datetime

    @classmethod
    def of(cls, o: Organization) -> "OrgOut":
        """Map an organization."""
        return cls(
            id=o.id,
            name=o.name,
            kind=o.kind,
            logo_url=o.logo_url,
            logo_zoom=o.logo_zoom,
            website=o.website,
            country=o.country,
            updated_at=o.updated_at,
        )


class OrgListOut(BaseModel):
    """Every organization and whether the caller manages them."""

    items: list[OrgOut]
    can_moderate: bool
