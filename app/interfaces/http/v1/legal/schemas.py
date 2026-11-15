"""Request and response bodies of the legal routes."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from app.modules.legal.application.queries import AcceptanceCount, PendingItem
from app.modules.legal.domain.models import LegalDocument

from pydantic import AfterValidator, BaseModel, Field

LegalKindValue = Literal["privacy", "terms", "biometric", "ai"]
MAX_TEXT = 200_000


def _bounded(texts: dict[str, str]) -> dict[str, str]:
    if any(len(text) > MAX_TEXT for text in texts.values()):
        raise ValueError(f"a text is longer than {MAX_TEXT} characters")
    return texts


LocaleTexts = Annotated[dict[str, str], AfterValidator(_bounded)]


class LegalDocumentOut(BaseModel):
    """The current published version of a kind, in one language."""

    kind: LegalKindValue
    version: int
    locale: str
    title: str
    body_markdown: str
    announcement: str | None
    published_at: datetime | None

    @classmethod
    def of(cls, document: LegalDocument, locale: str) -> "LegalDocumentOut":
        """Pick the texts of the locale."""
        return cls(
            kind=document.kind,
            version=document.version,
            locale=locale,
            title=document.title[locale],
            body_markdown=document.body_markdown[locale],
            announcement=document.announcement_for(locale),
            published_at=document.published_at,
        )


class LegalDocumentListOut(BaseModel):
    """Current documents, one per published kind."""

    items: list[LegalDocumentOut]


class PendingItemOut(LegalDocumentOut):
    """A document to accept; ``previously_accepted_version`` is null for a first."""

    previously_accepted_version: int | None

    @classmethod
    def of_pending(cls, item: PendingItem, locale: str) -> "PendingItemOut":
        """Pick the texts of the locale."""
        base = LegalDocumentOut.of(item.document, locale)
        return cls(
            **base.model_dump(),
            previously_accepted_version=item.previously_accepted_version,
        )


class PendingOut(BaseModel):
    """What the user has to accept; empty when nothing is pending."""

    items: list[PendingItemOut]

    @classmethod
    def of(cls, items: list[PendingItem], locale: str) -> "PendingOut":
        """Build from the pending items."""
        return cls(items=[PendingItemOut.of_pending(i, locale) for i in items])


class AcceptItemIn(BaseModel):
    """One accepted version."""

    kind: LegalKindValue
    version: int = Field(ge=1)


class AcceptIn(BaseModel):
    """Body of POST /v1/me/legal/accept; versions must be the current ones."""

    items: list[AcceptItemIn] = Field(min_length=1, max_length=8)


class AdminDocumentOut(BaseModel):
    """A version of a document with the texts of every language."""

    id: UUID
    kind: LegalKindValue
    version: int
    status: Literal["draft", "published"]
    title: dict[str, str]
    body_markdown: dict[str, str]
    announcement: dict[str, str] | None
    created_at: datetime
    updated_at: datetime
    published_at: datetime | None
    published_by: UUID | None

    @classmethod
    def of(cls, document: LegalDocument) -> "AdminDocumentOut":
        """Map the domain document."""
        return cls(
            id=document.id,
            kind=document.kind,
            version=document.version,
            status=document.status.value,
            title=document.title,
            body_markdown=document.body_markdown,
            announcement=document.announcement,
            created_at=document.created_at,
            updated_at=document.updated_at,
            published_at=document.published_at,
            published_by=document.published_by,
        )


class AdminDocumentListOut(BaseModel):
    """Every version of every kind, by kind then newest first."""

    items: list[AdminDocumentOut]


class DraftIn(BaseModel):
    """Body of PUT /v1/admin/legal/drafts/{kind}; keys are uz, ru and en."""

    title: LocaleTexts = Field(default_factory=dict)
    body_markdown: LocaleTexts = Field(default_factory=dict)
    announcement: LocaleTexts | None = None


class AcceptanceCountOut(BaseModel):
    """Users that accepted the current version of a kind."""

    kind: LegalKindValue
    version: int
    accepted_count: int

    @classmethod
    def of(cls, count: AcceptanceCount) -> "AcceptanceCountOut":
        """Map the application view."""
        return cls(
            kind=count.kind,
            version=count.version,
            accepted_count=count.accepted_count,
        )


class AcceptanceCountsOut(BaseModel):
    """One count per published kind."""

    items: list[AcceptanceCountOut]
