"""Organizations behind opportunities and scholarships (a tag with a logo)."""

import datetime as dt
from dataclasses import dataclass
from typing import Final, Literal, get_args
from uuid import UUID

OrgKind = Literal["university", "company", "foundation", "government", "ngo"]
ORG_KINDS: Final = get_args(OrgKind)
NAME_MAX: Final = 200
URL_MAX: Final = 2000
COUNTRY_MAX: Final = 100
ZOOM_MIN: Final = 0.5
ZOOM_MAX: Final = 3.0


@dataclass(frozen=True, slots=True)
class Organization:
    """A university, company, foundation, government body or NGO."""

    id: UUID
    name: str
    kind: OrgKind
    created_at: dt.datetime
    updated_at: dt.datetime
    logo_url: str | None = None
    logo_zoom: float = 1.0
    website: str | None = None
    country: str | None = None

    def problems(self) -> list[str]:
        """Return the names of the invalid fields (empty when valid)."""
        bad: list[str] = []
        if not self.name.strip() or len(self.name) > NAME_MAX:
            bad.append("name")
        if self.kind not in ORG_KINDS:
            bad.append("kind")
        if not ZOOM_MIN <= self.logo_zoom <= ZOOM_MAX:
            bad.append("logo_zoom")
        for field_name in ("logo_url", "website"):
            value = getattr(self, field_name)
            if value is not None and (
                len(value) > URL_MAX or not value.startswith("https://")
            ):
                bad.append(field_name)
        if self.country is not None and len(self.country) > COUNTRY_MAX:
            bad.append("country")
        return bad
