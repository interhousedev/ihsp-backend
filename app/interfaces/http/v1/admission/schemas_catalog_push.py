"""Request and response shapes of the catalog push routes."""

from typing import Any

from app.modules.admission.domain.catalog_push import (
    COUNTRY_BATCH_MAX,
    INSTITUTION_BATCH_MAX,
    PushResult,
    PushStatus,
)

from pydantic import BaseModel, Field


class CountryPushItemIn(BaseModel):
    """One country in the shape of `country_facts.json`; checked per item."""

    country: str = Field(max_length=8, description="ISO 3166-1 alpha-2 code.")
    as_of: str = Field(max_length=16, description="Month of the facts, `YYYY-MM`.")
    facts: dict[str, Any] = Field(
        description="Facts keyed by fact name, as `PUT .../countries/{code}` takes."
    )


class CountryPushIn(BaseModel):
    """A batch of countries, upserted by ISO code as drafts."""

    items: list[CountryPushItemIn] = Field(min_length=1, max_length=COUNTRY_BATCH_MAX)
    overwrite_verified: bool = Field(
        default=False, description="Replace countries a curator already verified."
    )


class InstitutionPushIn(BaseModel):
    """A batch of institutions in the seed catalog shape, upserted by slug."""

    items: list[dict[str, Any]] = Field(
        min_length=1,
        max_length=INSTITUTION_BATCH_MAX,
        description="Seed `Institution` entries, optionally with `logo_url`, "
        "`cover_url` (https; mirrored into our storage).",
    )


class PushResultOut(BaseModel):
    """What happened to one item of the batch."""

    index: int
    key: str = Field(description="ISO code or institution slug.")
    status: PushStatus
    field: str | None = Field(description="The invalid field when `invalid`.")
    warnings: list[str] = Field(
        description="Fields saved without their value, e.g. a logo not fetched."
    )

    @classmethod
    def of(cls, r: PushResult) -> "PushResultOut":
        """Map a result."""
        return cls(
            index=r.index,
            key=r.key,
            status=r.status,
            field=r.field,
            warnings=list(r.warnings),
        )


class PushResultListOut(BaseModel):
    """One result per pushed item, in order."""

    items: list[PushResultOut]

    @classmethod
    def of(cls, results: list[PushResult]) -> "PushResultListOut":
        """Map the results."""
        return cls(items=[PushResultOut.of(r) for r in results])
