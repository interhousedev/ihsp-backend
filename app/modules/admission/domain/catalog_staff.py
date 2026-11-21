"""Staff management views of the catalog: institutions and opportunity lists."""

import datetime as dt
from dataclasses import dataclass, field
from typing import Final, Literal
from uuid import UUID

InstitutionStatus = Literal["published", "provisional", "archived"]
OpportunityState = Literal["all", "live", "archived"]

INSTITUTION_STATUSES: Final = ("published", "provisional", "archived")
PAGE_MAX: Final = 100
PAGE_DEFAULT: Final = 25
QUERY_MAX: Final = 100


@dataclass(frozen=True, slots=True)
class StaffInstitution:
    """An institution as the staff table and edit form see it."""

    id: UUID
    name: str
    name_local: str | None
    country: str
    city: str | None
    website_domain: str | None
    kind: str
    size_band: str | None
    setting: str | None
    languages: tuple[str, ...]
    aliases: tuple[str, ...]
    status: InstitutionStatus
    logo_url: str | None
    cover_url: str | None
    logo_zoom: float
    logo_fit: str | None
    created_at: dt.datetime
    updated_at: dt.datetime
    lock_version: int
    in_use: bool = False


@dataclass(frozen=True, slots=True)
class InstitutionPage:
    """One page of institutions."""

    items: list[StaffInstitution]
    total: int
    countries: list[str] = field(default_factory=list)
    """Every country code present in the catalog, for the filter."""
