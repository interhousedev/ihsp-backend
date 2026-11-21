"""The institution catalog (§3.4)."""

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from app.modules.admission.infrastructure.orm._common import (
    CreatedMixin,
    LockMixin,
    S,
    UpdatedMixin,
    check_in,
    max_len,
)
from app.shared.db.base import Base, IdMixin

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

_INST = "admission.institutions.id"
_SRC = "admission.sources.id"


def _inst() -> Mapped[UUID]:
    return mapped_column(ForeignKey(_INST, ondelete="CASCADE"), index=True)


def _src() -> Mapped[UUID | None]:
    return mapped_column(ForeignKey(_SRC, ondelete="SET NULL"))


class SourceRow(IdMixin, CreatedMixin, UpdatedMixin, Base):
    """Where a fact comes from."""

    __tablename__ = "sources"
    __table_args__ = (
        check_in("kind", ("official_page", "structured_api", "dataset", "manual")),
        S,
    )

    kind: Mapped[str] = mapped_column(String(16))
    url: Mapped[str | None] = mapped_column(String(2000))
    licence: Mapped[str | None] = mapped_column(String(80))
    redistributable: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    refresh_sla_days: Mapped[int | None] = mapped_column(Integer)
    last_fetch_at: Mapped[datetime | None]
    snapshot_file_id: Mapped[UUID | None] = mapped_column(Uuid)


class InstitutionRow(IdMixin, CreatedMixin, UpdatedMixin, LockMixin, Base):
    """A university, college or foundation provider."""

    __tablename__ = "institutions"
    __table_args__ = (
        check_in("kind", ("university", "college", "foundation_provider")),
        CheckConstraint(
            "setting IS NULL OR setting IN"
            " ('big_city', 'college_town', 'campus', 'small_city')",
            name="setting",
        ),
        check_in("status", ("published", "provisional", "archived")),
        CheckConstraint(
            "(logo_url IS NULL OR logo_url LIKE 'https://%')"
            " AND (cover_url IS NULL OR cover_url LIKE 'https://%')",
            name="media_https",
        ),
        CheckConstraint("logo_zoom >= 0.5 AND logo_zoom <= 3", name="logo_zoom"),
        CheckConstraint(
            "logo_fit IS NULL OR logo_fit IN ('circle', 'contain')",
            name="logo_fit",
        ),
        Index(
            "ix_institutions_name_trgm",
            "name",
            postgresql_using="gin",
            postgresql_ops={"name": "gin_trgm_ops"},
        ),
        Index("ix_institutions_country", "country"),
        S,
    )

    slug: Mapped[str | None] = mapped_column(String(80), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    name_local: Mapped[str | None] = mapped_column(String(200))
    country: Mapped[str] = mapped_column(String(2))
    city: Mapped[str | None] = mapped_column(String(120))
    website_domain: Mapped[str | None] = mapped_column(String(200))
    ror_id: Mapped[str | None] = mapped_column(String(40))
    kind: Mapped[str] = mapped_column(String(20), server_default="university")
    size_band: Mapped[str | None] = mapped_column(String(10))
    setting: Mapped[str | None] = mapped_column(String(14))
    languages: Mapped[list[str]] = mapped_column(
        ARRAY(Text), server_default=text("'{}'")
    )
    status: Mapped[str] = mapped_column(String(12), server_default="provisional")
    logo_url: Mapped[str | None] = mapped_column(String(2000))
    cover_url: Mapped[str | None] = mapped_column(String(2000))
    aliases: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'"))
    logo_zoom: Mapped[float] = mapped_column(Float, server_default="1.0")
    logo_fit: Mapped[str | None] = mapped_column(String(8))
    logo_aspect: Mapped[float | None] = mapped_column(Float)


class CampusRow(IdMixin, CreatedMixin, UpdatedMixin, Base):
    """A campus of an institution."""

    __tablename__ = "campuses"
    __table_args__ = (S,)

    institution_id: Mapped[UUID] = _inst()
    name: Mapped[str] = mapped_column(String(200))
    country: Mapped[str] = mapped_column(String(2))
    city: Mapped[str | None] = mapped_column(String(120))
    is_branch: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    lat: Mapped[float | None] = mapped_column(Float)
    lon: Mapped[float | None] = mapped_column(Float)


class ProgramRow(IdMixin, CreatedMixin, UpdatedMixin, Base):
    """A study program."""

    __tablename__ = "programs"
    __table_args__ = (
        check_in("level", ("bachelor", "master", "foundation", "other", "2plus2")),
        max_len("school", 120),
        S,
    )

    institution_id: Mapped[UUID] = _inst()
    campus_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("admission.campuses.id", ondelete="SET NULL")
    )
    name: Mapped[str] = mapped_column(String(200))
    level: Mapped[str] = mapped_column(String(10))
    cip_code: Mapped[str | None] = mapped_column(String(10))
    language: Mapped[str | None] = mapped_column(String(8))
    duration_years: Mapped[Decimal | None] = mapped_column(Numeric(3, 1))
    school: Mapped[str | None] = mapped_column(String(120))
    field_ids: Mapped[list[str]] = mapped_column(
        ARRAY(Text), server_default=text("'{}'"), default=list
    )


class FactRow(IdMixin, CreatedMixin, UpdatedMixin, Base):
    """A sourced, reviewed fact about a catalog entity."""

    __tablename__ = "facts"
    __table_args__ = (
        check_in(
            "confidence", ("manual", "official", "structured_api", "ai_extracted")
        ),
        check_in("status", ("proposed", "published", "rejected", "stale")),
        max_len("excerpt", 300),
        Index("ix_facts_entity", "entity_kind", "entity_id", "key"),
        S,
    )

    entity_kind: Mapped[str] = mapped_column(String(20))
    entity_id: Mapped[UUID] = mapped_column(Uuid)
    key: Mapped[str] = mapped_column(String(60))
    value: Mapped[Any] = mapped_column(JSONB)
    unit: Mapped[str | None] = mapped_column(String(20))
    cycle: Mapped[int | None] = mapped_column(Integer)
    source_id: Mapped[UUID | None] = _src()
    excerpt: Mapped[str | None] = mapped_column(String(300))
    checked_at: Mapped[datetime | None]
    reviewer_id: Mapped[UUID | None] = mapped_column(Uuid)
    confidence: Mapped[str] = mapped_column(String(16))
    consequential: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    status: Mapped[str] = mapped_column(String(10), server_default="proposed")


class AdmissionStatRow(IdMixin, CreatedMixin, UpdatedMixin, Base):
    """Admission statistics of one cycle and cohort."""

    __tablename__ = "admission_stats"
    __table_args__ = (check_in("cohort", ("all", "international", "first_year")), S)

    institution_id: Mapped[UUID] = _inst()
    cycle: Mapped[int] = mapped_column(Integer)
    cohort: Mapped[str] = mapped_column(String(14))
    applicants: Mapped[int | None] = mapped_column(Integer)
    admits: Mapped[int | None] = mapped_column(Integer)
    enrolled: Mapped[int | None] = mapped_column(Integer)
    acceptance_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    tests: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'"))
    gpa_bands: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'")
    )
    test_submit_share: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    source_id: Mapped[UUID | None] = _src()


class AidPolicyRow(IdMixin, CreatedMixin, UpdatedMixin, Base):
    """Financial aid policy for international students."""

    __tablename__ = "aid_policies"
    __table_args__ = (
        check_in("intl_need_based", ("need_blind", "need_aware", "none", "unknown")),
        check_in("avg_aid_scope", ("intl", "overall")),
        CheckConstraint("grant_pct BETWEEN 0 AND 100", name="grant_pct"),
        CheckConstraint("loan_pct BETWEEN 0 AND 100", name="loan_pct"),
        CheckConstraint("work_pct BETWEEN 0 AND 100", name="work_pct"),
        S,
    )

    institution_id: Mapped[UUID] = _inst()
    cycle: Mapped[int] = mapped_column(Integer)
    intl_need_based: Mapped[str] = mapped_column(String(10), server_default="unknown")
    meets_full_need: Mapped[bool | None] = mapped_column(Boolean)
    merit_available: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    avg_aid: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    """Average aid package in USD; `avg_aid_scope` says whose average it is."""
    avg_aid_scope: Mapped[str | None] = mapped_column(String(8))
    grant_pct: Mapped[int | None] = mapped_column(SmallInteger)
    loan_pct: Mapped[int | None] = mapped_column(SmallInteger)
    work_pct: Mapped[int | None] = mapped_column(SmallInteger)
    forms: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'"))
    source_id: Mapped[UUID | None] = _src()


class CostOfAttendanceRow(IdMixin, CreatedMixin, UpdatedMixin, Base):
    """Cost of attendance in one currency."""

    __tablename__ = "costs_of_attendance"
    __table_args__ = (S,)

    institution_id: Mapped[UUID] = _inst()
    cycle: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3))
    tuition: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    housing: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    other: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    total: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    source_id: Mapped[UUID | None] = _src()


class RequirementRow(IdMixin, CreatedMixin, UpdatedMixin, Base):
    """An application requirement."""

    __tablename__ = "requirements"
    __table_args__ = (
        check_in(
            "international_policy",
            ("required", "optional", "not_considered", "unknown"),
        ),
        S,
    )

    institution_id: Mapped[UUID] = _inst()
    program_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("admission.programs.id", ondelete="CASCADE")
    )
    cycle: Mapped[int] = mapped_column(Integer)
    key: Mapped[str] = mapped_column(String(40))
    rule: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'"))
    international_policy: Mapped[str] = mapped_column(
        String(14), server_default="unknown"
    )
    source_id: Mapped[UUID | None] = _src()


class EligibilityRuleRow(IdMixin, CreatedMixin, UpdatedMixin, Base):
    """Curated (never AI-filled) eligibility of a national qualification."""

    __tablename__ = "eligibility_rules"
    __table_args__ = (
        check_in("outcome", ("direct", "foundation", "studienkolleg", "unknown")),
        S,
    )

    system: Mapped[str] = mapped_column(String(20))
    qualification: Mapped[str] = mapped_column(String(30))
    outcome: Mapped[str] = mapped_column(String(14))
    conditions: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'")
    )
    source_id: Mapped[UUID | None] = _src()
    reviewer_id: Mapped[UUID] = mapped_column(Uuid)


class RouteRow(IdMixin, CreatedMixin, UpdatedMixin, Base):
    """Application steps of a system (template keys)."""

    __tablename__ = "routes"
    __table_args__ = (S,)

    system: Mapped[str] = mapped_column(String(20))
    steps: Mapped[dict[str, Any]] = mapped_column(JSONB)
    version: Mapped[int] = mapped_column(Integer, server_default=text("1"))


class ScholarshipRow(IdMixin, CreatedMixin, UpdatedMixin, Base):
    """A scholarship."""

    __tablename__ = "scholarships"
    __table_args__ = (
        check_in("provider", ("institution", "government", "foundation")),
        check_in("basis", ("merit", "need", "government", "sports", "work_study")),
        check_in("status", ("published", "provisional")),
        S,
    )

    name: Mapped[str] = mapped_column(String(200))
    provider: Mapped[str] = mapped_column(String(12))
    institution_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(_INST, ondelete="CASCADE"), index=True
    )
    country: Mapped[str | None] = mapped_column(String(2))
    basis: Mapped[str] = mapped_column(String(12))
    coverage_pct_min: Mapped[int | None] = mapped_column(Integer)
    coverage_pct_max: Mapped[int | None] = mapped_column(Integer)
    covers: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'"))
    eligibility: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'")
    )
    deadline_id: Mapped[UUID | None] = mapped_column(Uuid)
    url: Mapped[str | None] = mapped_column(String(2000))
    source_id: Mapped[UUID | None] = _src()
    status: Mapped[str] = mapped_column(String(12), server_default="provisional")
    cycle: Mapped[int | None] = mapped_column(Integer)


class PlaceRow(IdMixin, CreatedMixin, UpdatedMixin, Base):
    """A country or city for safety facts."""

    __tablename__ = "places"
    __table_args__ = (check_in("level", ("country", "city")), S)

    country: Mapped[str] = mapped_column(String(2))
    city: Mapped[str | None] = mapped_column(String(120))
    level: Mapped[str] = mapped_column(String(8))


class SafetyFactRow(IdMixin, CreatedMixin, UpdatedMixin, Base):
    """A safety indicator of a place or campus."""

    __tablename__ = "safety_facts"
    __table_args__ = (
        check_in("level", ("country", "city", "campus")),
        check_in("indicator", ("travel_advisory", "gpi", "crime_rate", "clery")),
        CheckConstraint(
            "(place_id IS NULL) <> (campus_id IS NULL)", name="place_or_campus"
        ),
        S,
    )

    place_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("admission.places.id", ondelete="CASCADE")
    )
    campus_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("admission.campuses.id", ondelete="CASCADE")
    )
    level: Mapped[str] = mapped_column(String(8))
    indicator: Mapped[str] = mapped_column(String(16))
    value: Mapped[Decimal | None] = mapped_column(Numeric)
    band: Mapped[str | None] = mapped_column(String(16))
    band_version: Mapped[str | None] = mapped_column(String(20))
    uncertainty: Mapped[str | None] = mapped_column(String(20))
    year: Mapped[int | None] = mapped_column(Integer)
    source_id: Mapped[UUID | None] = _src()
    status: Mapped[str] = mapped_column(String(10), server_default="proposed")


class CatalogProposalRow(IdMixin, CreatedMixin, UpdatedMixin, LockMixin, Base):
    """A staff proposal to add or edit an institution or a scholarship."""

    __tablename__ = "catalog_proposals"
    __table_args__ = (
        check_in("kind", ("institution", "scholarship")),
        check_in("status", ("pending", "approved", "rejected")),
        Index("ix_catalog_proposals_status", "status", "created_at"),
        S,
    )

    kind: Mapped[str] = mapped_column(String(12))
    target_id: Mapped[UUID | None] = mapped_column(Uuid)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    source_url: Mapped[str] = mapped_column(String(2000))
    note: Mapped[str | None] = mapped_column(String(1000))
    status: Mapped[str] = mapped_column(String(10), server_default="pending")
    proposed_by: Mapped[UUID] = mapped_column(Uuid, index=True)
    reviewed_by: Mapped[UUID | None] = mapped_column(Uuid)
    reviewed_at: Mapped[datetime | None]
    review_note: Mapped[str | None] = mapped_column(String(500))
    applied_id: Mapped[UUID | None] = mapped_column(Uuid)
