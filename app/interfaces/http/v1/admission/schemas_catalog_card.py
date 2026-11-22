"""Schemas of the curator's institution card."""

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CardFactOut(BaseModel):
    """A stored fact in the editor's input shape."""

    key: str
    value: Any
    source_url: str | None
    year: int | None
    note: str | None
    verified: bool


class CardFactIn(BaseModel):
    """A fact to upsert; the value follows the key's kind."""

    model_config = ConfigDict(extra="forbid")

    value: Any
    source_url: str = Field(max_length=2000)
    year: int
    note: str | None = Field(default=None, max_length=300)
    verified: bool = True


class CardFactsPutIn(BaseModel):
    """Facts to upsert and keys to delete under the institution's lock."""

    model_config = ConfigDict(extra="forbid")

    lock_version: int
    facts: dict[str, CardFactIn] = {}
    remove: list[str] = []


class CardScholarshipOut(BaseModel):
    """A scholarship of the institution."""

    id: UUID
    name: str
    provider: Literal["institution", "government", "foundation"]
    basis: Literal["merit", "need", "government", "sports", "work_study"]
    country: str | None
    coverage_pct_min: int | None
    coverage_pct_max: int | None
    covers: list[str]
    url: str | None
    cycle: int | None


class CardScholarshipIn(BaseModel):
    """Scholarship fields; a create needs name, provider and basis."""

    model_config = ConfigDict(extra="forbid")

    lock_version: int
    name: str | None = Field(default=None, max_length=200)
    provider: Literal["institution", "government", "foundation"] | None = None
    basis: Literal["merit", "need", "government", "sports", "work_study"] | None = None
    country: str | None = Field(default=None, min_length=2, max_length=2)
    coverage_pct_min: int | None = Field(default=None, ge=0, le=100)
    coverage_pct_max: int | None = Field(default=None, ge=0, le=100)
    covers: list[str] | None = None
    url: str | None = Field(default=None, max_length=2000)
    cycle: int | None = None


class CardOut(BaseModel):
    """Facts, scholarships and description of one institution."""

    lock_version: int
    facts: list[CardFactOut]
    scholarships: list[CardScholarshipOut]
    description: dict[str, str]


class CardLockOut(BaseModel):
    """The institution's lock after a write."""

    lock_version: int


class CardDescriptionIn(BaseModel):
    """Description per locale (uz, ru, en); empty text clears a locale."""

    model_config = ConfigDict(extra="forbid")

    lock_version: int
    description: dict[str, str]
