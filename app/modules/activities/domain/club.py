"""Club aggregate: lifecycle, capabilities and declarations."""

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any
from uuid import UUID

from app.modules.activities.domain.errors import Conflict, Denied, Invalid

__all__ = [
    "SLUG_RE",
    "CapabilityDeniedError",
    "CapabilityDisabledError",
    "Club",
    "ClubCapability",
    "ClubInvalidError",
    "ClubKind",
    "ClubStateError",
    "ClubStatus",
    "Declaration",
    "JoinPolicy",
    "next_declaration",
]

SLUG_RE = re.compile(r"[a-z0-9][a-z0-9-]{2,39}")


class ClubKind(StrEnum):
    """Student club or an SU body."""

    CLUB = "club"
    SU = "su"


class ClubStatus(StrEnum):
    """Club lifecycle."""

    DRAFT = "draft"
    PENDING_REVIEW = "pending_review"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    ARCHIVED = "archived"


class JoinPolicy(StrEnum):
    """How people join."""

    OPEN = "open"
    REQUEST = "request"
    INVITE = "invite"


class ClubCapability(StrEnum):
    """Optional abilities that only SU switches on."""

    FORMS = "forms"
    DRAFTING = "drafting"
    POINTS = "points"
    ROSTER = "roster"


class ClubInvalidError(Invalid):
    """A club field is invalid."""


class ClubStateError(Conflict):
    """The club's state does not allow this."""


class CapabilityDeniedError(Denied):
    """Only SU toggles capabilities."""


class CapabilityDisabledError(Conflict):
    """The club does not have this capability."""


@dataclass(slots=True)
class Club:
    """A club."""

    id: UUID
    slug: str
    kind: ClubKind
    name: Any
    created_by: UUID
    status: ClubStatus = ClubStatus.DRAFT
    join_policy: JoinPolicy = JoinPolicy.OPEN
    visibility_public: bool = True
    contact_enabled: bool = False
    logo_file_id: UUID | None = None
    published_once: bool = False
    capabilities: frozenset[ClubCapability] = frozenset()
    description: str = ""
    owner_id: UUID | None = None
    has_minor_members: bool = False

    def validate(self) -> None:
        """Raise `ClubInvalidError` for a bad slug."""
        if not SLUG_RE.fullmatch(self.slug):
            raise ClubInvalidError(params={"field": "slug"})

    def submit(self) -> None:
        """Send a draft to review."""
        if self.status != ClubStatus.DRAFT:
            raise ClubStateError(params={"status": str(self.status)})
        self.validate()
        self.status = ClubStatus.PENDING_REVIEW

    def review(self, approve: bool, reason: str | None, by_su: bool) -> None:
        """SU approves or sends the club back to draft."""
        if not by_su or self.status != ClubStatus.PENDING_REVIEW:
            raise ClubStateError(params={"status": str(self.status)})
        if approve:
            self.status = ClubStatus.ACTIVE
            self.published_once = True
            return
        if not (reason or "").strip():
            raise ClubInvalidError(params={"field": "reason"})
        self.status = ClubStatus.DRAFT

    def suspend(self) -> None:
        """Hide an active club."""
        if self.status != ClubStatus.ACTIVE:
            raise ClubStateError(params={"status": str(self.status)})
        self.status = ClubStatus.SUSPENDED

    def archive(self) -> None:
        """Close an active club."""
        if self.status != ClubStatus.ACTIVE:
            raise ClubStateError(params={"status": str(self.status)})
        self.status = ClubStatus.ARCHIVED

    def rename_slug(self, new: str) -> None:
        """Change the slug while the club was never published."""
        if self.published_once:
            raise ClubStateError(params={"field": "slug"})
        if not SLUG_RE.fullmatch(new):
            raise ClubInvalidError(params={"field": "slug"})
        self.slug = new

    def enable(self, cap: ClubCapability, *, by_su: bool) -> None:
        """Switch a capability on; drafting brings forms."""
        if not by_su:
            raise CapabilityDeniedError()
        caps = set(self.capabilities) | {cap}
        if cap == ClubCapability.DRAFTING:
            caps.add(ClubCapability.FORMS)
        self.capabilities = frozenset(caps)

    def disable(self, cap: ClubCapability, *, by_su: bool) -> None:
        """Switch a capability off."""
        if not by_su:
            raise CapabilityDeniedError()
        self.capabilities = frozenset(self.capabilities - {cap})

    def set_capabilities(self, caps: set[ClubCapability], *, by_su: bool) -> None:
        """Replace the whole set."""
        if not by_su:
            raise CapabilityDeniedError()
        full = set(caps)
        if ClubCapability.DRAFTING in full:
            full.add(ClubCapability.FORMS)
        self.capabilities = frozenset(full)

    def require(self, cap: ClubCapability) -> None:
        """Raise `CapabilityDisabledError` when the capability is off."""
        if cap not in self.capabilities:
            raise CapabilityDisabledError(params={"capability": cap.value})


@dataclass(frozen=True, slots=True)
class Declaration:
    """A versioned club charter; never edited, only superseded."""

    club_id: UUID
    version: int
    goals: Any
    rules: Any
    meeting_schedule: Any
    requirements: Any
    extra: dict[str, Any] = field(default_factory=dict)


def next_declaration(
    previous: Declaration | None,
    *,
    club_id: UUID | None = None,
    goals: Any,
    rules: Any,
    meeting_schedule: Any,
    requirements: Any,
) -> Declaration:
    """The next version of a declaration."""
    cid = previous.club_id if previous else club_id
    if cid is None:
        raise ClubInvalidError(params={"field": "club_id"})
    return Declaration(
        cid,
        (previous.version if previous else 0) + 1,
        goals,
        rules,
        meeting_schedule,
        requirements,
    )
