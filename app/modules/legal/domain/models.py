"""Legal documents: kinds, versions, drafts and publication rules."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from app.shared.contracts.legal import GLOBAL_APP


class LegalKind(StrEnum):
    """What a document regulates."""

    PRIVACY = "privacy"
    TERMS = "terms"
    BIOMETRIC = "biometric"
    AI = "ai"
    ADMISSION_PRIVACY = "admission_privacy"
    ADMISSION_TERMS = "admission_terms"
    ADMISSION_DISCLAIMER = "admission_disclaimer"


class DocumentStatus(StrEnum):
    """A draft is editable; a published version is frozen."""

    DRAFT = "draft"
    PUBLISHED = "published"


DocKey = tuple[str, str]
"""A document series: (kind, app_scope)."""

LOCALES = ("uz", "ru", "en")
KINDS = tuple(k.value for k in LegalKind)
ADMISSION_SCOPE = "admission"
STAFF_ROLES = frozenset(
    {
        "teacher",
        "admin",
        "lms_admin",
        "lms_creator",
        "librarian",
        "counselor",
        "mentor",
        "transcript_officer",
    }
)


def kind_fits_scope(kind: str, app_scope: str) -> bool:
    """Admission kinds belong to the admission app and to nothing else."""
    return app_scope == ADMISSION_SCOPE or not kind.startswith("admission_")


def guardian_attestation_required(roles: Iterable[str]) -> bool:
    """Whether accepting an app document needs a guardian's attestation.

    The identity module keeps no birth date, and a flag from the client is not
    trusted, so every account that is not staff is treated as a possible minor.
    """
    return not (set(roles) & STAFF_ROLES)


@dataclass(slots=True)
class LegalDocument:
    """One version of a document; texts are keyed by locale (uz, ru, en)."""

    id: UUID
    kind: str
    version: int
    status: DocumentStatus
    title: dict[str, str]
    body_markdown: dict[str, str]
    announcement: dict[str, str] | None
    created_at: datetime
    updated_at: datetime
    published_at: datetime | None = None
    published_by: UUID | None = None
    app_scope: str = GLOBAL_APP

    def missing_fields(self) -> list[str]:
        """Fields that block publication (a title and a body in every locale)."""
        missing = []
        for locale in LOCALES:
            if not self.title.get(locale, "").strip():
                missing.append(f"title.{locale}")
            if not self.body_markdown.get(locale, "").strip():
                missing.append(f"body_markdown.{locale}")
        return missing

    def announcement_for(self, locale: str) -> str | None:
        """The "what changed" text in the locale, if any."""
        if not self.announcement:
            return None
        return self.announcement.get(locale, "").strip() or None


@dataclass(frozen=True, slots=True)
class Acceptance:
    """A user accepted a version. Rows are only ever inserted."""

    id: UUID
    user_id: UUID
    kind: str
    version: int
    accepted_at: datetime
    ip: str | None
    user_agent: str | None
    app_scope: str = GLOBAL_APP
    guardian_attested: bool = False
