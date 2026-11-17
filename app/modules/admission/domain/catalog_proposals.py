"""Staff proposals to change the catalog (§11): reviewed before they go live."""

import datetime as dt
from dataclasses import dataclass, field
from typing import Any, Final, Literal
from uuid import UUID

ProposalKind = Literal["institution", "scholarship"]
ProposalStatus = Literal["pending", "approved", "rejected"]

INSTITUTION_FIELDS: Final = frozenset(
    {
        "name",
        "name_local",
        "country",
        "city",
        "website_domain",
        "kind",
        "size_band",
        "setting",
        "languages",
        "logo_url",
        "logo_zoom",
        "logo_fit",
        "logo_aspect",
        "aliases",
        "cover_url",
    }
)
SCHOLARSHIP_FIELDS: Final = frozenset(
    {
        "name",
        "provider",
        "institution_id",
        "country",
        "basis",
        "coverage_pct_min",
        "coverage_pct_max",
        "covers",
        "eligibility",
        "url",
        "cycle",
    }
)
FIELDS: Final = {"institution": INSTITUTION_FIELDS, "scholarship": SCHOLARSHIP_FIELDS}
MEDIA_FIELDS: Final = ("logo_url", "cover_url")
"""Institution fields that hold an https image address."""
REQUIRED_ON_CREATE: Final = {
    "institution": frozenset({"name", "country"}),
    "scholarship": frozenset({"name", "provider", "basis"}),
}


@dataclass(frozen=True, slots=True)
class CatalogProposal:
    """One proposal; `target_id` is set when it edits an existing row."""

    id: UUID
    kind: ProposalKind
    target_id: UUID | None
    payload: dict[str, Any]
    source_url: str
    note: str | None
    status: ProposalStatus
    proposed_by: UUID
    created_at: dt.datetime
    lock_version: int = 0
    reviewed_by: UUID | None = None
    reviewed_at: dt.datetime | None = None
    review_note: str | None = None
    applied_id: UUID | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def missing_on_create(self) -> list[str]:
        """Return the required fields a new row still lacks."""
        if self.target_id is not None:
            return []
        have = {k for k, v in self.payload.items() if v not in (None, "")}
        return sorted(REQUIRED_ON_CREATE[self.kind] - have)
