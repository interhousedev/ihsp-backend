"""Legal documents: kinds, versions, drafts and publication rules."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class LegalKind(StrEnum):
    """What a document regulates."""

    PRIVACY = "privacy"
    TERMS = "terms"
    BIOMETRIC = "biometric"
    AI = "ai"


class DocumentStatus(StrEnum):
    """A draft is editable; a published version is frozen."""

    DRAFT = "draft"
    PUBLISHED = "published"


LOCALES = ("uz", "ru", "en")
KINDS = tuple(k.value for k in LegalKind)


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
