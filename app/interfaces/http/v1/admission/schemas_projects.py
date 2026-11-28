"""Request and response shapes of the project-ideas and helper routes."""

import datetime as dt
from typing import Literal
from uuid import UUID

from app.modules.admission.application.project_ideas import RunOverview
from app.modules.admission.domain.project_ideas import (
    HELP_TAGS,
    HELP_TYPES,
    Analog,
    Brief,
    Helper,
    HelpTag,
    HelpType,
    ProjectIdea,
    ProjectRun,
)

from pydantic import BaseModel, ConfigDict, Field


class BriefIn(BaseModel):
    """What the student tells about themselves."""

    model_config = ConfigDict(extra="forbid")

    likes: str = Field(min_length=1, max_length=1500)
    experience: str = Field(default="", max_length=1500)
    hours_per_day: float = Field(ge=0.25, le=16)
    teammates: Literal["yes", "maybe", "no"]
    teammates_note: str = Field(default="", max_length=300)
    network: str = Field(default="", max_length=1000)
    budget_min_usd: int = Field(ge=0, le=1_000_000)
    budget_max_usd: int = Field(ge=0, le=1_000_000)
    future_interest: str = Field(default="", max_length=1500)

    @classmethod
    def of(cls, brief: Brief) -> "BriefIn":
        """Project a stored brief."""
        return cls(
            likes=brief.likes,
            experience=brief.experience,
            hours_per_day=brief.hours_per_day,
            teammates=brief.teammates,
            teammates_note=brief.teammates_note,
            network=brief.network,
            budget_min_usd=brief.budget_min_usd,
            budget_max_usd=brief.budget_max_usd,
            future_interest=brief.future_interest,
        )


class AnalogOut(BaseModel):
    """An existing project like the idea."""

    name: str
    where: Literal["uzbekistan", "abroad"]
    url: str | None

    @classmethod
    def of(cls, analog: Analog) -> "AnalogOut":
        """Project a stored analog."""
        return cls(
            name=analog.name,
            where=analog.where,
            url=analog.url,
        )


class ProjectOut(BaseModel):
    """One suggested project."""

    key: str
    title: str
    summary: str
    analogs: list[AnalogOut]
    challenges: list[str]
    application_effect: str
    first_steps: list[str]
    help_tags: list[HelpTag]
    deliverable: str = ""
    measure: str = ""
    why_you: str = ""
    weeks: int | None = None

    @classmethod
    def of(cls, idea: ProjectIdea) -> "ProjectOut":
        """Project a stored idea."""
        return cls(
            key=idea.key,
            title=idea.title,
            summary=idea.summary,
            analogs=[AnalogOut.of(a) for a in idea.analogs],
            challenges=list(idea.challenges),
            application_effect=idea.application_effect,
            first_steps=list(idea.first_steps),
            help_tags=list(idea.help_tags),
            deliverable=idea.deliverable,
            measure=idea.measure,
            why_you=idea.why_you,
            weeks=idea.weeks,
        )


class ProjectRunOut(BaseModel):
    """One generation of ideas."""

    id: UUID
    created_at: dt.datetime
    search_used: bool
    brief: BriefIn
    projects: list[ProjectOut]

    @classmethod
    def of(cls, run: ProjectRun) -> "ProjectRunOut":
        """Project a stored run."""
        return cls(
            id=run.id,
            created_at=run.created_at,
            search_used=run.search_used,
            brief=BriefIn.of(run.brief),
            projects=[ProjectOut.of(p) for p in run.projects],
        )


class RunSummaryOut(BaseModel):
    """One earlier run in the history list."""

    id: UUID
    created_at: dt.datetime
    count: int


class ProjectIdeasOut(BaseModel):
    """The newest run and the kept history."""

    latest: ProjectRunOut | None
    history: list[RunSummaryOut]

    @classmethod
    def of(cls, overview: RunOverview) -> "ProjectIdeasOut":
        """Project the overview."""
        return cls(
            latest=ProjectRunOut.of(overview.latest) if overview.latest else None,
            history=[
                RunSummaryOut(id=r.id, created_at=r.created_at, count=r.count)
                for r in overview.history
            ],
        )


class HelperText(BaseModel):
    """A description in the three languages (a missing one is empty)."""

    model_config = ConfigDict(extra="forbid")

    en: str = ""
    ru: str = ""
    uz: str = ""


class HelperContacts(BaseModel):
    """How to reach a helper; at least one is set."""

    model_config = ConfigDict(extra="forbid")

    email: str | None = None
    phone: str | None = None
    telegram: str | None = None
    website: str | None = None


class HelperIn(BaseModel):
    """A curator's helper."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["person", "organization"]
    name: str = Field(min_length=1, max_length=200)
    description: HelperText
    tags: list[HelpTag] = Field(min_length=1, max_length=len(HELP_TAGS))
    help_types: list[HelpType] = Field(max_length=len(HELP_TYPES))
    expertise_areas: list[str] = Field(max_length=12)
    contacts: HelperContacts
    city: str | None = Field(default=None, max_length=120)
    active: bool = True

    def values(self) -> dict[str, object]:
        """The editable fields as plain values."""
        return self.model_dump()


class HelperOut(HelperIn):
    """A stored helper."""

    id: UUID

    @classmethod
    def of(cls, helper: Helper) -> "HelperOut":
        """Project a stored helper."""
        return cls(
            id=helper.id,
            kind=helper.kind,
            name=helper.name,
            description=HelperText(**dict(helper.description)),
            tags=list(helper.tags),
            help_types=list(helper.help_types),
            expertise_areas=list(helper.expertise_areas),
            contacts=HelperContacts(
                email=helper.contacts.email,
                phone=helper.contacts.phone,
                telegram=helper.contacts.telegram,
                website=helper.contacts.website,
            ),
            city=helper.city,
            active=helper.active,
        )


class HelperListOut(BaseModel):
    """Helpers."""

    items: list[HelperOut]
