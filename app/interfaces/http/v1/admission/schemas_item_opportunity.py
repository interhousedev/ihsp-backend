"""Schemas of the activity opportunity link and the "not in the list" lookup."""

from typing import Any, Literal, Self
from uuid import UUID

from app.modules.admission.application.item_opportunity import (
    QUERY_MAX,
    ItemOpportunityView,
    Lookup,
)
from app.modules.admission.application.opportunity_intake import IntakeDraft
from app.modules.admission.domain.opportunities import OpportunityDraft

from pydantic import BaseModel, Field


class IntakeDraftIO(BaseModel):
    """A researched draft; the student may edit it before linking."""

    title: str = Field(max_length=200)
    summary: str = Field(default="", max_length=1200)
    provider: str = Field(default="", max_length=200)
    kind: str = Field(default="event", max_length=20)
    registration_deadlines: list[str] = Field(default_factory=list, max_length=12)
    event_dates: list[str] = Field(default_factory=list, max_length=12)
    recurrence: str = Field(default="", max_length=120)
    subject_ids: list[str] = Field(default_factory=list, max_length=12)
    url: str = Field(default="", max_length=500)
    materials: list[dict[str, str]] = Field(default_factory=list, max_length=6)
    missing: list[str] = Field(default_factory=list)
    blocked: list[str] = Field(default_factory=list)

    @classmethod
    def of(cls, d: IntakeDraft) -> Self:
        """From the intake draft."""
        return cls(**d.to_dict())

    def draft(self) -> IntakeDraft:
        """To the intake draft."""
        data: dict[str, Any] = self.model_dump()
        return IntakeDraft.from_dict(data)


class OpportunityBriefOut(BaseModel):
    """The current basics of an entry or a proposal."""

    title: str
    provider: str | None
    kind: str
    url: str | None
    summary: str | None

    @classmethod
    def of(cls, d: OpportunityDraft) -> Self:
        """From a draft."""
        return cls(
            title=d.title,
            provider=d.provider,
            kind=d.kind,
            url=d.url,
            summary=d.summary,
        )


class OpportunityMatchOut(OpportunityBriefOut):
    """A catalog entry that looks like the lookup."""

    id: UUID


class OpportunityLookupIn(BaseModel):
    """One line: a link, or a name and an organization."""

    query: str = Field(min_length=2, max_length=QUERY_MAX)
    locale: Literal["uz", "ru", "en"] = "en"


class OpportunityLookupOut(BaseModel):
    """The draft, similar catalog entries and a pending twin proposal."""

    draft: IntakeDraftIO
    matches: list[OpportunityMatchOut]
    pending_submission_id: UUID | None

    @classmethod
    def of(cls, r: Lookup) -> Self:
        """From the service result."""
        return cls(
            draft=IntakeDraftIO.of(r.draft),
            matches=[
                OpportunityMatchOut(
                    id=o.id, **OpportunityBriefOut.of(o.draft).model_dump()
                )
                for o in r.matches
            ],
            pending_submission_id=r.pending.id if r.pending else None,
        )


class ItemOpportunityIn(BaseModel):
    """Exactly one: an existing entry or a new (researched) draft."""

    opportunity_id: UUID | None = None
    draft: IntakeDraftIO | None = None


class ItemOpportunityOut(BaseModel):
    """The opportunity of an activity; `verified` once a moderator approved it."""

    item_id: UUID
    status: Literal["pending", "verified", "rejected"]
    opportunity_id: UUID | None
    submission_id: UUID | None
    opportunity: OpportunityBriefOut
    reason: str | None

    @classmethod
    def of(cls, v: ItemOpportunityView) -> Self:
        """From the view."""
        return cls(
            item_id=v.item_id,
            status=v.status,
            opportunity_id=v.opportunity_id,
            submission_id=v.submission_id,
            opportunity=OpportunityBriefOut.of(v.draft),
            reason=v.reason,
        )


class ItemOpportunityEnvelope(BaseModel):
    """The link, or null."""

    link: ItemOpportunityOut | None
