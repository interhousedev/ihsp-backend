"""Profile, items, reviews, proofs, essays, comments and courses (§3.2)."""

from datetime import date, datetime
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
    Date,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

_F = "admission.items.id"


class ProfileRow(UpdatedMixin, CreatedMixin, LockMixin, Base):
    """One admission profile per student."""

    __tablename__ = "profiles"
    __table_args__ = (
        check_in("stage", ("setup", "words", "items", "chooser", "docs", "submitted")),
        check_in("account_kind", ("student", "alumni")),
        CheckConstraint(
            "aid_need IS NULL OR aid_need IN ('none', 'partial', 'full')",
            name="aid_need",
        ),
        check_in("academics_source", ("emis", "self_reported")),
        max_len("helper_display_name", 60),
        S,
    )

    student_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    account_kind: Mapped[str] = mapped_column(String(8), server_default="student")
    cycle: Mapped[int | None] = mapped_column(Integer)
    stage: Mapped[str] = mapped_column(String(12), server_default="setup")
    question_set_version: Mapped[str] = mapped_column(String(40))
    answers: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'"))
    intended_majors: Mapped[list[str]] = mapped_column(
        ARRAY(Text), server_default=text("'{}'")
    )
    minors: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'"))
    career_plan: Mapped[str | None] = mapped_column(Text)
    budget_band: Mapped[str | None] = mapped_column(String(16))
    aid_need: Mapped[str | None] = mapped_column(String(8))
    fee_waiver_need: Mapped[bool | None] = mapped_column(Boolean)
    finance_visible_to_counselor: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false")
    )
    academics_source: Mapped[str] = mapped_column(String(16), server_default="emis")
    mentee_opt_in: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    mentor_opt_in: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    helper_opt_in: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    helper_display_name: Mapped[str | None] = mapped_column(String(60))
    setup_completed_at: Mapped[datetime | None]


class ProfileWordsRow(UpdatedMixin, CreatedMixin, LockMixin, Base):
    """The three words that describe the student."""

    __tablename__ = "profile_words"
    __table_args__ = (
        check_in("source", ("ai", "manual", "mixed")),
        CheckConstraint("cardinality(words) <= 3", name="words_count"),
        S,
    )

    student_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    words: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'"))
    candidates: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'")
    )
    source: Mapped[str] = mapped_column(String(8), server_default="manual")
    version: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    confirmed_at: Mapped[datetime | None]


class ProfileWordsHistoryRow(CreatedMixin, UpdatedMixin, Base):
    """Earlier confirmed word sets."""

    __tablename__ = "profile_words_history"
    __table_args__ = (S,)

    student_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    words: Mapped[list[str]] = mapped_column(ARRAY(Text))
    confirmed_at: Mapped[datetime | None]


class ItemRow(IdMixin, CreatedMixin, UpdatedMixin, LockMixin, Base):
    """An activity or honor in Common App limits."""

    __tablename__ = "items"
    __table_args__ = (
        check_in("kind", ("activity", "honor")),
        check_in("status", ("draft", "ready")),
        max_len("position", 60),
        max_len("org", 100),
        CheckConstraint(
            "char_length(description) <= "
            "CASE WHEN kind = 'honor' THEN 100 ELSE 150 END",
            name="description_length",
        ),
        Index("ix_items_student_id_sort_order", "student_id", "sort_order"),
        S,
    )

    student_id: Mapped[UUID] = mapped_column(Uuid)
    kind: Mapped[str] = mapped_column(String(8))
    position: Mapped[str] = mapped_column(String(60))
    org: Mapped[str] = mapped_column(String(100), server_default="")
    description: Mapped[str] = mapped_column(String(150), server_default="")
    category: Mapped[str | None] = mapped_column(String(40))
    grade_levels: Mapped[list[int]] = mapped_column(
        ARRAY(Integer), server_default=text("'{}'")
    )
    hours_week: Mapped[int | None] = mapped_column(Integer)
    weeks_year: Mapped[int | None] = mapped_column(Integer)
    started_on: Mapped[date | None] = mapped_column(Date)
    role: Mapped[str | None] = mapped_column(String(100))
    outcome: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    status: Mapped[str] = mapped_column(String(8), server_default="draft")
    timing: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'"))
    intend_in_college: Mapped[bool | None] = mapped_column(Boolean)
    ai_grade: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class ItemMetricRow(IdMixin, CreatedMixin, UpdatedMixin, Base):
    """A measurable result of an item."""

    __tablename__ = "item_metrics"
    __table_args__ = (
        check_in("horizon", ("current", "projected")),
        check_in(
            "provenance",
            ("self_stated", "source_supported", "independently_verified"),
        ),
        CheckConstraint(
            "horizon <> 'projected' OR target_date IS NOT NULL", name="projected_date"
        ),
        S,
    )

    item_id: Mapped[UUID] = mapped_column(
        ForeignKey(_F, ondelete="CASCADE"), index=True
    )
    label: Mapped[str] = mapped_column(String(80))
    value: Mapped[Decimal] = mapped_column(Numeric)
    unit: Mapped[str | None] = mapped_column(String(24))
    horizon: Mapped[str] = mapped_column(String(10))
    as_of: Mapped[date | None] = mapped_column(Date)
    target_date: Mapped[date | None] = mapped_column(Date)
    provenance: Mapped[str] = mapped_column(String(24), server_default="self_stated")
    evidence_claim_id: Mapped[UUID | None] = mapped_column(Uuid)


class ItemInterviewRow(IdMixin, CreatedMixin, UpdatedMixin, Base):
    """One AI interview round about an item (at most 3)."""

    __tablename__ = "item_interviews"
    __table_args__ = (CheckConstraint("round BETWEEN 1 AND 3", name="round"), S)

    item_id: Mapped[UUID] = mapped_column(
        ForeignKey(_F, ondelete="CASCADE"), index=True
    )
    round: Mapped[int] = mapped_column(Integer)
    questions: Mapped[dict[str, Any]] = mapped_column(JSONB)
    answers: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'"))


class GoalMilestoneRow(IdMixin, CreatedMixin, UpdatedMixin, LockMixin, Base):
    """A step of the goal plan."""

    __tablename__ = "goal_milestones"
    __table_args__ = (
        check_in("status", ("planned", "done", "dropped")),
        check_in("source", ("ai", "manual")),
        max_len("title", 120),
        CheckConstraint(
            "due_month IS NULL OR extract(day FROM due_month) = 1",
            name="due_month_first_day",
        ),
        S,
    )

    student_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    item_id: Mapped[UUID | None] = mapped_column(ForeignKey(_F, ondelete="SET NULL"))
    metric_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("admission.item_metrics.id", ondelete="SET NULL")
    )
    title: Mapped[str] = mapped_column(String(120))
    due_month: Mapped[date | None] = mapped_column(Date)
    target_value: Mapped[Decimal | None] = mapped_column(Numeric)
    status: Mapped[str] = mapped_column(String(8), server_default="planned")
    done_at: Mapped[datetime | None]
    source: Mapped[str] = mapped_column(String(8), server_default="manual")
    sort_order: Mapped[int] = mapped_column(Integer, server_default=text("0"))


class ReviewRow(IdMixin, CreatedMixin, UpdatedMixin, Base):
    """A cached AI review of an item, essay or alignment."""

    __tablename__ = "reviews"
    __table_args__ = (
        check_in("target_kind", ("item", "essay", "alignment")),
        check_in("safety_flag", ("none", "injection_suspected", "safeguarding")),
        check_in("status", ("ready", "in_flight", "failed")),
        UniqueConstraint(
            "target_kind", "target_id", "input_hash", name="uq_reviews_input"
        ),
        Index("ix_reviews_student_id", "student_id"),
        S,
    )

    student_id: Mapped[UUID] = mapped_column(Uuid)
    target_kind: Mapped[str] = mapped_column(String(10))
    target_id: Mapped[UUID] = mapped_column(Uuid)
    input_hash: Mapped[str] = mapped_column(String(64))
    task: Mapped[str] = mapped_column(String(40))
    model: Mapped[str | None] = mapped_column(String(80))
    prompt_version: Mapped[str] = mapped_column(String(40))
    rubric_version: Mapped[str | None] = mapped_column(String(40))
    schema_version: Mapped[str] = mapped_column(String(40))
    words_version: Mapped[int | None] = mapped_column(Integer)
    grades: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'"))
    overall: Mapped[str | None] = mapped_column(String(1))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'"))
    safety_flag: Mapped[str] = mapped_column(String(20), server_default="none")
    status: Mapped[str] = mapped_column(String(10), server_default="in_flight")


class ReviewFeedbackRow(IdMixin, CreatedMixin, UpdatedMixin, Base):
    """A student's reaction to a review."""

    __tablename__ = "review_feedback"
    __table_args__ = (check_in("kind", ("unfair", "helpful")), max_len("note", 500), S)

    review_id: Mapped[UUID] = mapped_column(
        ForeignKey("admission.reviews.id", ondelete="CASCADE"), index=True
    )
    student_id: Mapped[UUID] = mapped_column(Uuid)
    kind: Mapped[str] = mapped_column(String(8))
    note: Mapped[str | None] = mapped_column(String(500))


class ProofRow(IdMixin, CreatedMixin, UpdatedMixin, LockMixin, Base):
    """Evidence for an item."""

    __tablename__ = "proofs"
    __table_args__ = (
        check_in("kind", ("linkedin", "telegram", "website", "file", "self_provided")),
        CheckConstraint(
            "extraction IS NULL OR extraction IN ('html', 'pdf_text', 'ocr', 'pasted')",
            name="extraction",
        ),
        check_in("status", ("pending", "checked", "unverifiable", "failed")),
        S,
    )

    item_id: Mapped[UUID] = mapped_column(
        ForeignKey(_F, ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(16))
    url: Mapped[str | None] = mapped_column(String(2000))
    file_id: Mapped[UUID | None] = mapped_column(Uuid)
    text_sha256: Mapped[str | None] = mapped_column(String(64))
    extraction: Mapped[str | None] = mapped_column(String(10))
    fetched_at: Mapped[datetime | None]
    next_check_at: Mapped[datetime | None]
    status: Mapped[str] = mapped_column(String(14), server_default="pending")


class ProofClaimRow(IdMixin, CreatedMixin, UpdatedMixin, Base):
    """One claim checked against a proof."""

    __tablename__ = "proof_claims"
    __table_args__ = (
        check_in(
            "status",
            (
                "source_supported",
                "partial",
                "not_found",
                "contradicted",
                "unverifiable",
            ),
        ),
        max_len("quote", 300),
        S,
    )

    proof_id: Mapped[UUID] = mapped_column(
        ForeignKey("admission.proofs.id", ondelete="CASCADE"), index=True
    )
    metric_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("admission.item_metrics.id", ondelete="SET NULL")
    )
    claim_text: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(18))
    matched: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'"))
    quote: Mapped[str | None] = mapped_column(String(300))
    checked_at: Mapped[datetime | None]
    superseded_by: Mapped[UUID | None] = mapped_column(Uuid)


class EssayRow(IdMixin, UpdatedMixin, CreatedMixin, LockMixin, Base):
    """An essay; `list_entry_id` null is the personal statement."""

    __tablename__ = "essays"
    __table_args__ = (
        check_in("status", ("draft", "final")),
        check_in("kind", ("personal_statement", "supplemental", "other")),
        S,
    )

    student_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    list_entry_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("admission.list_entries.id", ondelete="SET NULL")
    )
    prompt_text: Mapped[str] = mapped_column(Text, server_default="")
    word_limit: Mapped[int | None] = mapped_column(Integer)
    current_version: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    body: Mapped[bytes] = mapped_column(LargeBinary)  # sealed
    status: Mapped[str] = mapped_column(String(8), server_default="draft")
    kind: Mapped[str] = mapped_column(String(20), server_default="personal_statement")
    title: Mapped[bytes] = mapped_column(LargeBinary)  # sealed
    notes: Mapped[bytes] = mapped_column(LargeBinary)  # sealed
    plan: Mapped[bytes] = mapped_column(LargeBinary)  # sealed JSON list
    links: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, server_default=text("'[]'")
    )
    last_snapshot_at: Mapped[datetime | None]


class EssayVersionRow(IdMixin, CreatedMixin, UpdatedMixin, Base):
    """A saved essay version."""

    __tablename__ = "essay_versions"
    __table_args__ = (
        UniqueConstraint("essay_id", "version", name="uq_essay_versions_version"),
        check_in("source", ("interval", "explicit", "restore")),
        S,
    )

    essay_id: Mapped[UUID] = mapped_column(
        ForeignKey("admission.essays.id", ondelete="CASCADE")
    )
    version: Mapped[int] = mapped_column(Integer)
    name: Mapped[bytes | None] = mapped_column(LargeBinary)  # sealed
    body: Mapped[bytes] = mapped_column(LargeBinary)  # sealed
    created_by: Mapped[UUID] = mapped_column(Uuid)
    source: Mapped[str] = mapped_column(String(10), server_default="explicit")
    shared: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    word_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))


class EssayIdeaRow(IdMixin, UpdatedMixin, CreatedMixin, LockMixin, Base):
    """A brainstorm card of the ideas board."""

    __tablename__ = "essay_ideas"
    __table_args__ = (
        check_in("status", ("explore", "keep", "drop")),
        S,
    )

    student_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    essay_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("admission.essays.id", ondelete="CASCADE"), index=True
    )
    body: Mapped[bytes] = mapped_column(LargeBinary)  # sealed
    tags: Mapped[bytes] = mapped_column(LargeBinary)  # sealed JSON list
    status: Mapped[str] = mapped_column(String(8), server_default="explore")
    sort_order: Mapped[int] = mapped_column(Integer, server_default=text("0"))


class CommentRow(IdMixin, CreatedMixin, UpdatedMixin, Base):
    """A comment on a student's object."""

    __tablename__ = "comments"
    __table_args__ = (
        check_in(
            "target_kind",
            ("profile", "item", "list_entry", "essay", "words", "help_request"),
        ),
        check_in("visibility", ("student_and_staff", "staff_only")),
        max_len("body", 2000),
        Index("ix_comments_target", "target_kind", "target_id"),
        S,
    )

    student_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    target_kind: Mapped[str] = mapped_column(String(12))
    target_id: Mapped[UUID] = mapped_column(Uuid)
    anchor: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    author_id: Mapped[UUID] = mapped_column(Uuid)
    body: Mapped[str] = mapped_column(Text)
    visibility: Mapped[str] = mapped_column(String(20))
    deleted_at: Mapped[datetime | None]


class CourseRow(IdMixin, CreatedMixin, UpdatedMixin, Base):
    """A course on the profile (addendum: courses).

    Holds stored LMS snapshots, manual rows, and the `included` flag of live
    academic subjects.
    """

    __tablename__ = "courses"
    __table_args__ = (
        check_in("source", ("academic", "lms", "manual")),
        CheckConstraint(
            "source = 'manual' OR source_ref IS NOT NULL", name="source_ref"
        ),
        Index(
            "uq_courses_source_ref",
            "student_id",
            "source",
            "source_ref",
            unique=True,
            postgresql_where=text("source_ref IS NOT NULL"),
        ),
        max_len("title", 200),
        S,
    )

    student_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    source: Mapped[str] = mapped_column(String(8))
    source_ref: Mapped[str | None] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(200))
    provider: Mapped[str | None] = mapped_column(String(120))
    level: Mapped[str | None] = mapped_column(String(40))
    year: Mapped[int | None] = mapped_column(Integer)
    grade: Mapped[str | None] = mapped_column(String(20))
    included: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
