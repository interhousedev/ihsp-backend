"""Sponsors and partners of a club or of the whole platform."""

from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from uuid import UUID

from app.modules.activities.domain.errors import Invalid

__all__ = ["Partner", "PartnerInvalidError", "PartnerKind"]


class PartnerKind(StrEnum):
    """What the partner is."""

    SPONSOR = "sponsor"
    PARTNER = "partner"
    MEDIA = "media"


class PartnerInvalidError(Invalid):
    """A partner field is invalid."""


@dataclass(slots=True)
class Partner:
    """A partner shown on public pages."""

    club_id: UUID | None
    name: str
    kind: PartnerKind
    logo_file_id: UUID | None
    url: str | None
    tier: str | None
    since: date
    until: date | None
    public: bool
    logo_approved: bool = True

    def validate(self) -> None:
        """Name 1..100 characters; the link, when set, is https."""
        if not 1 <= len(self.name.strip()) <= 100:
            raise PartnerInvalidError(params={"field": "name"})
        if self.url is not None and not self.url.startswith("https://"):
            raise PartnerInvalidError(params={"field": "url"})

    def is_active(self, today: date) -> bool:
        """Inside the partnership window."""
        return self.since <= today and (self.until is None or self.until >= today)

    def is_public_visible(self, today: date) -> bool:
        """Public, active and with an approved logo."""
        return self.public and self.is_active(today) and self.logo_approved
