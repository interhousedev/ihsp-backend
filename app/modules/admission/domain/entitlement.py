"""Who may enter the admission app (§4.1)."""

from dataclasses import dataclass
from typing import Final, Literal
from uuid import UUID

from app.modules.admission.domain.access import Entitlement, IneligibleReason
from app.modules.admission.domain.permissions import KIND_ROLE
from app.shared.actor import Role

ActorKind = Literal["applicant", "staff", "none"]
# Administrators enter the staff area too (settings, student list, saved views).
STAFF_ROLES: Final = frozenset({*KIND_ROLE.values(), Role.ADMIN})
ELIGIBLE_GRADES: Final = frozenset({10, 11})


@dataclass(frozen=True, slots=True)
class AdmissionActor:
    """The caller as the admission app sees it; computed once per request."""

    user_id: UUID
    entitlement: Entitlement | None
    staff_roles: frozenset[Role]

    @property
    def is_applicant(self) -> bool:
        """Return whether the caller may use the student side."""
        return self.entitlement is not None and self.entitlement.is_applicant

    @property
    def is_staff(self) -> bool:
        """Return whether the caller holds an admission staff role."""
        return bool(self.staff_roles)

    @property
    def kind(self) -> ActorKind:
        """Classify the caller; applicant wins over staff for the default view."""
        if self.is_applicant:
            return "applicant"
        if self.is_staff:
            return "staff"
        return "none"

    @property
    def may_enter(self) -> bool:
        """Return whether any admission route besides `/me` is reachable."""
        return self.kind != "none"

    def ineligible_reason(self, grade: int | None) -> IneligibleReason | None:
        """Return why the caller cannot use the student side, if they cannot."""
        if self.is_applicant:
            return None
        if grade is not None and grade not in ELIGIBLE_GRADES:
            return "not_in_grade"
        return "no_entitlement"


def admission_staff_roles(roles: frozenset[Role]) -> frozenset[Role]:
    """Return the admission staff roles among the user's global roles."""
    return roles & STAFF_ROLES


def grade_from_group_name(name: str | None) -> int | None:
    """Read the grade from a lyceum group name such as `10-A` or `11B`."""
    if not name:
        return None
    digits = ""
    for ch in name.strip():
        if ch.isdigit():
            digits += ch
        else:
            break
    return int(digits) if digits else None
