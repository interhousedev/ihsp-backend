"""Applications, checklist, deadlines and documents (§3.5)."""

from datetime import datetime, time
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
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    Time,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

_ENTRY = "admission.list_entries.id"
_INST = "admission.institutions.id"
LIST_STATUSES = (
    "considering",
    "applying",
    "submitted",
    "admitted",
    "waitlisted",
    "deferred",
    "rejected",
    "enrolled",
    "withdrawn",
)
ROUNDS = ("RD", "EA", "ED", "ED2", "REA", "rolling", "other")
DOC_KINDS = (
    "transcript",
    "school_report",
    "rec",
    "certificate",
    "passport",
    "translation",
    "test_report",
    "bank",
    "other",
)


class PreferenceRow(CreatedMixin, UpdatedMixin, Base):
    """A versioned snapshot of the chooser answers."""

    __tablename__ = "preferences"
    __table_args__ = (S,)

    student_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    answers: Mapped[dict[str, Any]] = mapped_column(JSONB)


class DeckDecisionRow(IdMixin, CreatedMixin, UpdatedMixin, Base):
    """A swipe decision of the chooser deck."""

    __tablename__ = "deck_decisions"
    __table_args__ = (check_in("decision", ("shortlist", "hide")), S)

    student_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    institution_id: Mapped[UUID] = mapped_column(ForeignKey(_INST, ondelete="CASCADE"))
    decision: Mapped[str] = mapped_column(String(10))
    reason_chip: Mapped[str | None] = mapped_column(String(40))
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    undone_at: Mapped[datetime | None]


class ListEntryRow(IdMixin, CreatedMixin, UpdatedMixin, LockMixin, Base):
    """One institution on the student's list."""

    __tablename__ = "list_entries"
    __table_args__ = (
        check_in("round", ROUNDS),
        check_in("status", LIST_STATUSES),
        CheckConstraint(
            "label_override IS NULL OR label_override IN"
            " ('reach', 'target', 'safety')",
            name="label_override",
        ),
        check_in("affordability_status", ("feasible", "gap", "unknown", "signed_off")),
        max_len("override_note", 300),
        S,
    )

    student_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    institution_id: Mapped[UUID] = mapped_column(ForeignKey(_INST, ondelete="RESTRICT"))
    campus_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("admission.campuses.id", ondelete="SET NULL")
    )
    program_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("admission.programs.id", ondelete="SET NULL")
    )
    round: Mapped[str] = mapped_column(String(8), server_default="RD")
    status: Mapped[str] = mapped_column(String(12), server_default="considering")
    decision_at: Mapped[datetime | None]
    aid_offer: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    estimate: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    label_override: Mapped[str | None] = mapped_column(String(8))
    override_note: Mapped[str | None] = mapped_column(Text)
    override_by: Mapped[UUID | None] = mapped_column(Uuid)
    override_at: Mapped[datetime | None]
    bucket: Mapped[str | None] = mapped_column(String(8))
    notes: Mapped[str | None] = mapped_column(String(1000))
    affordability_status: Mapped[str] = mapped_column(
        String(10), server_default="unknown"
    )
    eligibility_outcome: Mapped[str | None] = mapped_column(String(14))


class AffordabilityCheckRow(IdMixin, CreatedMixin, UpdatedMixin, LockMixin, Base):
    """The affordability arithmetic of one list entry."""

    __tablename__ = "affordability_checks"
    __table_args__ = (
        check_in("status", ("feasible", "gap", "unknown")),
        max_len("sign_off_note", 300),
        S,
    )

    list_entry_id: Mapped[UUID] = mapped_column(
        ForeignKey(_ENTRY, ondelete="CASCADE"), index=True
    )
    coa_total: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    confirmed_aid: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    estimated_aid: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    family_band: Mapped[str | None] = mapped_column(String(16))
    enrolment_deposit: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    fees_total: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    gap: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    status: Mapped[str] = mapped_column(String(10), server_default="unknown")
    requested_sign_off_at: Mapped[datetime | None]
    signed_off_by: Mapped[UUID | None] = mapped_column(Uuid)
    signed_off_at: Mapped[datetime | None]
    sign_off_note: Mapped[str | None] = mapped_column(Text)


class DeadlineRow(IdMixin, CreatedMixin, UpdatedMixin, Base):
    """A versioned institution deadline."""

    __tablename__ = "deadlines"
    __table_args__ = (
        check_in("precision", ("date_only", "instant")),
        check_in("status", ("confirmed", "predicted", "unknown", "confirm_with_uni")),
        max_len("source_text", 200),
        Index("ix_deadlines_institution_cycle", "institution_id", "cycle"),
        S,
    )

    institution_id: Mapped[UUID] = mapped_column(ForeignKey(_INST, ondelete="CASCADE"))
    program_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("admission.programs.id", ondelete="CASCADE")
    )
    cycle: Mapped[int] = mapped_column(Integer)
    round: Mapped[str] = mapped_column(String(8))
    precision: Mapped[str] = mapped_column(String(10), server_default="date_only")
    source_text: Mapped[str | None] = mapped_column(Text)
    source_tz: Mapped[str | None] = mapped_column(String(40))
    local_date: Mapped[Any | None] = mapped_column(Date)
    cutoff_time: Mapped[time | None] = mapped_column(Time)
    instant_utc: Mapped[datetime | None]
    binding: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    applies_to: Mapped[str | None] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(16), server_default="unknown")
    source_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("admission.sources.id", ondelete="SET NULL")
    )
    version: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    superseded_by: Mapped[UUID | None] = mapped_column(Uuid)


class MilestoneRow(IdMixin, CreatedMixin, UpdatedMixin, Base):
    """A dated step of one list entry."""

    __tablename__ = "milestones"
    __table_args__ = (
        check_in(
            "kind",
            ("application", "aid", "test_send", "rec", "docs", "decision")
            + ("deposit", "fee"),
        ),
        S,
    )

    list_entry_id: Mapped[UUID] = mapped_column(
        ForeignKey(_ENTRY, ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(12))
    due_utc: Mapped[datetime | None]
    deadline_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("admission.deadlines.id", ondelete="SET NULL")
    )
    deadline_version: Mapped[int | None] = mapped_column(Integer)
    predicted: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))


class ChecklistItemRow(IdMixin, CreatedMixin, UpdatedMixin, LockMixin, Base):
    """A checklist line of a student or list entry."""

    __tablename__ = "checklist_items"
    __table_args__ = (
        check_in("owner", ("student", "counselor", "officer", "teacher")),
        check_in("status", ("todo", "in_progress", "done", "n_a", "confirm_with_uni")),
        Index(
            "uq_checklist_items_template",
            "student_id",
            "list_entry_id",
            "template_key",
            unique=True,
            postgresql_nulls_not_distinct=True,
        ),
        S,
    )

    student_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    list_entry_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(_ENTRY, ondelete="CASCADE")
    )
    template_key: Mapped[str] = mapped_column(String(60))
    title_key: Mapped[str] = mapped_column(String(80))
    owner: Mapped[str] = mapped_column(String(10), server_default="student")
    status: Mapped[str] = mapped_column(String(16), server_default="todo")
    due_utc: Mapped[datetime | None]
    document_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("admission.documents.id", ondelete="SET NULL")
    )
    source_url: Mapped[str | None] = mapped_column(String(2000))
    rule_version: Mapped[int] = mapped_column(Integer, server_default=text("1"))


class DocumentRow(IdMixin, CreatedMixin, UpdatedMixin, LockMixin, Base):
    """A student document; confidential ones are institution-owned."""

    __tablename__ = "documents"
    __table_args__ = (
        check_in("kind", DOC_KINDS),
        check_in("visibility", ("student", "confidential")),
        check_in("owner_kind", ("student", "institution")),
        check_in("review_status", ("none", "accepted", "rejected")),
        max_len("reject_note", 300),
        S,
    )

    student_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    kind: Mapped[str] = mapped_column(String(14))
    current_version: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    visibility: Mapped[str] = mapped_column(String(12), server_default="student")
    owner_kind: Mapped[str] = mapped_column(String(12), server_default="student")
    uploaded_by: Mapped[UUID] = mapped_column(Uuid)
    review_status: Mapped[str] = mapped_column(String(10), server_default="none")
    reject_reason_code: Mapped[str | None] = mapped_column(String(40))
    reject_note: Mapped[str | None] = mapped_column(Text)
    reviewed_by: Mapped[UUID | None] = mapped_column(Uuid)
    reviewed_at: Mapped[datetime | None]


class DocumentVersionRow(IdMixin, CreatedMixin, UpdatedMixin, Base):
    """One uploaded file version of a document."""

    __tablename__ = "document_versions"
    __table_args__ = (
        check_in(
            "scan_status", ("pending_scan", "clean", "infected", "failed", "unscanned")
        ),
        Index(
            "uq_document_versions_doc_version", "document_id", "version", unique=True
        ),
        S,
    )

    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("admission.documents.id", ondelete="CASCADE")
    )
    version: Mapped[int] = mapped_column(Integer)
    file_id: Mapped[UUID] = mapped_column(Uuid)
    scan_status: Mapped[str] = mapped_column(String(12), server_default="pending_scan")
    uploaded_by: Mapped[UUID] = mapped_column(Uuid)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


class DocumentAttachmentRow(IdMixin, CreatedMixin, UpdatedMixin, Base):
    """A document version attached to an application."""

    __tablename__ = "document_attachments"
    __table_args__ = (
        check_in("status", ("attached", "superseded", "detached")),
        Index(
            "uq_document_attachments_live",
            "document_id",
            "list_entry_id",
            unique=True,
            postgresql_where=text("status = 'attached'"),
        ),
        S,
    )

    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("admission.documents.id", ondelete="CASCADE")
    )
    document_version: Mapped[int] = mapped_column(Integer)
    list_entry_id: Mapped[UUID] = mapped_column(
        ForeignKey(_ENTRY, ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(10), server_default="attached")
    attached_by: Mapped[UUID] = mapped_column(Uuid)
    attached_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


class TranscriptRequestRow(IdMixin, CreatedMixin, UpdatedMixin, LockMixin, Base):
    """A request to the registrar for a transcript."""

    __tablename__ = "transcript_requests"
    __table_args__ = (
        check_in("status", ("requested", "ready", "cancelled")),
        max_len("destination_note", 200),
        Index(
            "uq_transcript_requests_open",
            "student_id",
            unique=True,
            postgresql_where=text("status = 'requested'"),
        ),
        S,
    )

    student_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    destination_note: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(10), server_default="requested")
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    ready_at: Mapped[datetime | None]
    ready_by: Mapped[UUID | None] = mapped_column(Uuid)
    undo_until: Mapped[datetime | None]
    pickup_location_snapshot: Mapped[str | None] = mapped_column(Text)
    cancelled_by: Mapped[UUID | None] = mapped_column(Uuid)
    cancelled_at: Mapped[datetime | None]
    last_reminded_at: Mapped[datetime | None]
    document_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("admission.documents.id", ondelete="SET NULL")
    )


class ReminderPrefsRow(CreatedMixin, UpdatedMixin, LockMixin, Base):
    """Reminder preferences of a student."""

    __tablename__ = "reminder_prefs"
    __table_args__ = (
        CheckConstraint(
            "offsets_days <@ ARRAY[60, 30, 14, 7, 3, 1]", name="offsets_days"
        ),
        CheckConstraint(
            "channels <@ ARRAY['telegram', 'push', 'email']::text[]", name="channels"
        ),
        S,
    )

    student_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    offsets_days: Mapped[list[int]] = mapped_column(
        ARRAY(Integer), server_default=text("'{60,30,14,7,3,1}'")
    )
    channels: Mapped[list[str]] = mapped_column(
        ARRAY(Text), server_default=text("'{telegram,push,email}'")
    )
    quiet_from: Mapped[time] = mapped_column(Time, server_default=text("'22:00'"))
    quiet_to: Mapped[time] = mapped_column(Time, server_default=text("'08:00'"))


class ReminderRow(IdMixin, CreatedMixin, UpdatedMixin, Base):
    """A scheduled deadline reminder."""

    __tablename__ = "reminders"
    __table_args__ = (S,)

    student_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    milestone_id: Mapped[UUID] = mapped_column(
        ForeignKey("admission.milestones.id", ondelete="CASCADE")
    )
    schedule_version: Mapped[int] = mapped_column(Integer)
    offset_days: Mapped[int] = mapped_column(Integer)
    dedupe_key: Mapped[str] = mapped_column(String(160), unique=True)
    scheduled_at: Mapped[datetime]
    sent_at: Mapped[datetime | None]
    failed_at: Mapped[datetime | None]
    superseded_at: Mapped[datetime | None]
