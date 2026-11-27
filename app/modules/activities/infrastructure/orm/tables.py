"""ORM models of the activities schema: clubs, events, drafting, points, team."""

from datetime import datetime
from typing import Any
from uuid import UUID

from app.shared.db.base import Base, TimestampMixin

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column


class _Stamped(TimestampMixin, Base):
    """Base of every activities table: created_at and updated_at."""

    __abstract__ = True


S = {"schema": "activities"}
_NOW = text("now()")


def _in(column: str, values: tuple[str, ...]) -> CheckConstraint:
    quoted = ", ".join(f"'{v}'" for v in values)
    return CheckConstraint(f"{column} IN ({quoted})", name=column)


def _ts() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=_NOW)


def _uuid_pk() -> Mapped[UUID]:
    return mapped_column(Uuid, primary_key=True)


class ClubRow(_Stamped):
    """A club or an SU body."""

    __tablename__ = "activities_clubs"
    __table_args__ = (
        UniqueConstraint("slug"),
        _in("kind", ("club", "su")),
        _in(
            "status",
            ("draft", "pending_review", "active", "suspended", "archived"),
        ),
        _in("join_policy", ("open", "request", "invite")),
        S,
    )

    id: Mapped[UUID] = _uuid_pk()
    slug: Mapped[str] = mapped_column(String(40))
    kind: Mapped[str] = mapped_column(String(8))
    name: Mapped[Any] = mapped_column(JSONB)
    created_by: Mapped[UUID] = mapped_column(Uuid)
    status: Mapped[str] = mapped_column(String(16))
    join_policy: Mapped[str] = mapped_column(String(8))
    visibility_public: Mapped[bool] = mapped_column(Boolean)
    contact_enabled: Mapped[bool] = mapped_column(Boolean)
    logo_file_id: Mapped[UUID | None] = mapped_column(Uuid)
    published_once: Mapped[bool] = mapped_column(Boolean)
    capabilities: Mapped[list[str]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb")
    )
    description: Mapped[str] = mapped_column(Text, server_default="")
    owner_id: Mapped[UUID | None] = mapped_column(Uuid)
    has_minor_members: Mapped[bool] = mapped_column(Boolean)
    category: Mapped[str] = mapped_column(String(40), server_default="")
    goals: Mapped[str] = mapped_column(Text, server_default="")
    rules: Mapped[str] = mapped_column(Text, server_default="")
    schedule: Mapped[str] = mapped_column(Text, server_default="")
    partners: Mapped[list[str]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb")
    )
    form_fields: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb")
    )
    points_rules: Mapped[dict[str, int]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = _ts()


class DeclarationRow(_Stamped):
    """A versioned club charter."""

    __tablename__ = "activities_declarations"
    __table_args__ = (S,)

    club_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    goals: Mapped[Any] = mapped_column(JSONB)
    rules: Mapped[Any] = mapped_column(JSONB)
    meeting_schedule: Mapped[Any] = mapped_column(JSONB)
    requirements: Mapped[Any] = mapped_column(JSONB)
    extra: Mapped[dict[str, Any]] = mapped_column(JSONB)


class MembershipRow(_Stamped):
    """A person's place in a club."""

    __tablename__ = "activities_memberships"
    __table_args__ = (
        _in("role", ("owner", "co_owner", "team", "member")),
        _in("status", ("requested", "active", "left", "removed", "banned")),
        Index(
            "uq_activities_memberships_one_owner",
            "club_id",
            unique=True,
            postgresql_where=text("role = 'owner' AND status = 'active'"),
        ),
        Index("ix_activities_memberships_user", "user_id"),
        S,
    )

    club_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    user_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    role: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(10))
    declaration_version: Mapped[int] = mapped_column(Integer)
    joined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    left_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TransferRow(_Stamped):
    """An ownership transfer offer."""

    __tablename__ = "activities_transfers"
    __table_args__ = (
        _in("status", ("offered", "accepted", "declined", "cancelled", "expired")),
        Index("ix_activities_transfers_club", "club_id"),
        S,
    )

    id: Mapped[UUID] = _uuid_pk()
    club_id: Mapped[UUID] = mapped_column(Uuid)
    from_user: Mapped[UUID] = mapped_column(Uuid)
    to_user: Mapped[UUID] = mapped_column(Uuid)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(10))


class EventRow(_Stamped):
    """A club event."""

    __tablename__ = "activities_events"
    __table_args__ = (
        _in("status", ("draft", "scheduled", "cancelled", "done")),
        _in("rsvp_policy", ("open", "members", "approval")),
        Index("ix_activities_events_club", "club_id", "starts_at"),
        Index("ix_activities_events_opportunity", "opportunity_id"),
        S,
    )

    id: Mapped[UUID] = _uuid_pk()
    club_id: Mapped[UUID] = mapped_column(Uuid)
    title: Mapped[Any] = mapped_column(JSONB)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    capacity: Mapped[int | None] = mapped_column(Integer)
    rsvp_policy: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(10))
    description: Mapped[Any] = mapped_column(JSONB, nullable=True)
    location: Mapped[str | None] = mapped_column(String(300))
    course_id: Mapped[UUID | None] = mapped_column(Uuid)
    opportunity_id: Mapped[UUID | None] = mapped_column(Uuid)
    schedule_revision: Mapped[int] = mapped_column(Integer)
    rating_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    created_by: Mapped[UUID | None] = mapped_column(Uuid)


class RsvpRow(_Stamped):
    """A person's place at an event."""

    __tablename__ = "activities_rsvps"
    __table_args__ = (UniqueConstraint("event_id", "user_id"), S)

    id: Mapped[UUID] = _uuid_pk()
    event_id: Mapped[UUID] = mapped_column(Uuid)
    user_id: Mapped[UUID] = mapped_column(Uuid)
    status: Mapped[str] = mapped_column(String(12))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    checked_in_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    check_in_method: Mapped[str | None] = mapped_column(String(10))
    event_role: Mapped[str | None] = mapped_column(String(40))


class EventReportRow(_Stamped):
    """The report of a finished event."""

    __tablename__ = "activities_event_reports"
    __table_args__ = (S,)

    event_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    attendance_count: Mapped[int] = mapped_column(Integer)
    summary: Mapped[str] = mapped_column(Text)
    media_file_ids: Mapped[list[str]] = mapped_column(JSONB)
    outcomes: Mapped[list[str]] = mapped_column(JSONB)
    published: Mapped[bool] = mapped_column(Boolean)


class RatingRow(_Stamped):
    """A rating of an event or a club."""

    __tablename__ = "activities_ratings"
    __table_args__ = (
        _in("target_type", ("event", "club")),
        Index("ix_activities_ratings_target", "target_type", "target_id"),
        S,
    )

    id: Mapped[UUID] = _uuid_pk()
    target_type: Mapped[str] = mapped_column(String(8))
    target_id: Mapped[UUID] = mapped_column(Uuid)
    user_id: Mapped[UUID] = mapped_column(Uuid)
    score: Mapped[int] = mapped_column(Integer)
    aspects: Mapped[dict[str, int]] = mapped_column(JSONB)
    comment: Mapped[str | None] = mapped_column(Text)
    anonymous_to_club: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AnnouncementRow(_Stamped):
    """A club announcement."""

    __tablename__ = "activities_announcements"
    __table_args__ = (Index("ix_activities_announcements_club", "club_id"), S)

    id: Mapped[UUID] = _uuid_pk()
    club_id: Mapped[UUID] = mapped_column(Uuid)
    author_id: Mapped[UUID] = mapped_column(Uuid)
    text: Mapped[str] = mapped_column(Text)
    audience: Mapped[str] = mapped_column(String(60))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    recipient_count: Mapped[int] = mapped_column(Integer)
    cancelled: Mapped[bool] = mapped_column(Boolean)


class PlannerRow(_Stamped):
    """A planner board item."""

    __tablename__ = "activities_planner_items"
    __table_args__ = (
        _in("status", ("backlog", "planned", "doing", "done")),
        Index("ix_activities_planner_items_club", "club_id"),
        S,
    )

    id: Mapped[UUID] = _uuid_pk()
    club_id: Mapped[UUID] = mapped_column(Uuid)
    kind: Mapped[str] = mapped_column(String(20))
    title: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text)
    assignee_id: Mapped[UUID | None] = mapped_column(Uuid)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(10))
    event_id: Mapped[UUID | None] = mapped_column(Uuid)
    term: Mapped[str] = mapped_column(String(20))


class DraftRoundRow(_Stamped):
    """A call for volunteers for one event."""

    __tablename__ = "activities_draft_rounds"
    __table_args__ = (Index("ix_activities_draft_rounds_club", "club_id"), S)

    id: Mapped[UUID] = _uuid_pk()
    event_id: Mapped[UUID] = mapped_column(Uuid)
    club_id: Mapped[UUID] = mapped_column(Uuid)
    needed: Mapped[dict[str, int]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(10))


class DraftSignupRow(_Stamped):
    """A member's offer for a role."""

    __tablename__ = "activities_draft_signups"
    __table_args__ = (Index("ix_activities_draft_signups_round", "round_id"), S)

    id: Mapped[UUID] = _uuid_pk()
    round_id: Mapped[UUID] = mapped_column(Uuid)
    user_id: Mapped[UUID] = mapped_column(Uuid)
    role: Mapped[str] = mapped_column(String(60))
    answers: Mapped[dict[str, Any]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(12))


class DraftPickRow(_Stamped):
    """An organizer's pick."""

    __tablename__ = "activities_draft_picks"
    __table_args__ = (
        _in(
            "status",
            ("proposed", "invited", "accepted", "declined", "completed", "no_show"),
        ),
        Index("ix_activities_draft_picks_round", "round_id"),
        S,
    )

    id: Mapped[UUID] = _uuid_pk()
    round_id: Mapped[UUID] = mapped_column(Uuid)
    user_id: Mapped[UUID] = mapped_column(Uuid)
    role: Mapped[str] = mapped_column(String(60))
    status: Mapped[str] = mapped_column(String(10))


class ClubProfileRow(_Stamped):
    """A member's reusable answers per club."""

    __tablename__ = "activities_club_profiles"
    __table_args__ = (S,)

    user_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    club_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    answers: Mapped[dict[str, Any]] = mapped_column(JSONB)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PointsRow(_Stamped):
    """The points ledger; one award per source, person and reason."""

    __tablename__ = "activities_points_ledger"
    __table_args__ = (
        UniqueConstraint("source_type", "source_id", "user_id", "reason"),
        Index("ix_activities_points_ledger_club", "club_id", "user_id"),
        S,
    )

    id: Mapped[UUID] = _uuid_pk()
    user_id: Mapped[UUID] = mapped_column(Uuid)
    source_type: Mapped[str] = mapped_column(String(40))
    source_id: Mapped[UUID] = mapped_column(Uuid)
    reason: Mapped[str] = mapped_column(String(40))
    points: Mapped[int] = mapped_column(Integer)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    club_id: Mapped[UUID | None] = mapped_column(Uuid)


class PointsOptOutRow(_Stamped):
    """People who hide their name on leaderboards."""

    __tablename__ = "activities_points_optout"
    __table_args__ = (S,)

    user_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)


class PositionRow(_Stamped):
    """A team position."""

    __tablename__ = "activities_positions"
    __table_args__ = (Index("ix_activities_positions_club", "club_id"), S)

    id: Mapped[UUID] = _uuid_pk()
    club_id: Mapped[UUID] = mapped_column(Uuid)
    title: Mapped[Any] = mapped_column(JSONB)
    description: Mapped[Any] = mapped_column(JSONB)
    slots: Mapped[int] = mapped_column(Integer)
    open_for_applications: Mapped[bool] = mapped_column(Boolean)
    form_schema: Mapped[dict[str, Any]] = mapped_column(JSONB)
    order: Mapped[int] = mapped_column("position_order", Integer)


class ApplicationRow(_Stamped):
    """An application to a position."""

    __tablename__ = "activities_position_applications"
    __table_args__ = (
        Index("ix_activities_position_applications_position", "position_id"),
        S,
    )

    id: Mapped[UUID] = _uuid_pk()
    position_id: Mapped[UUID] = mapped_column(Uuid)
    user_id: Mapped[UUID] = mapped_column(Uuid)
    answers: Mapped[dict[str, Any]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(12))
    note: Mapped[str | None] = mapped_column(Text)


class SeatRow(_Stamped):
    """A person on the team."""

    __tablename__ = "activities_team_seats"
    __table_args__ = (Index("ix_activities_team_seats_position", "position_id"), S)

    id: Mapped[UUID] = _uuid_pk()
    position_id: Mapped[UUID] = mapped_column(Uuid)
    user_id: Mapped[UUID] = mapped_column(Uuid)
    since: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    public: Mapped[bool] = mapped_column(Boolean)
    consent_public: Mapped[bool] = mapped_column(Boolean)
    bio: Mapped[Any] = mapped_column(JSONB, nullable=True)
    experience: Mapped[list[Any]] = mapped_column(JSONB)
    photo_url: Mapped[str | None] = mapped_column(String(2000))
    consent_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ConsentEventRow(_Stamped):
    """The consent history."""

    __tablename__ = "activities_consent_events"
    __table_args__ = (Index("ix_activities_consent_events_user", "user_id"), S)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    user_id: Mapped[UUID] = mapped_column(Uuid)
    granted: Mapped[bool] = mapped_column(Boolean)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ClubCourseRow(_Stamped):
    """A club-course link."""

    __tablename__ = "activities_club_courses"
    __table_args__ = (
        UniqueConstraint("club_id", "course_id"),
        _in("status", ("pending", "active", "ended")),
        Index("ix_activities_club_courses_course", "course_id"),
        S,
    )

    id: Mapped[UUID] = _uuid_pk()
    club_id: Mapped[UUID] = mapped_column(Uuid)
    course_id: Mapped[UUID] = mapped_column(Uuid)
    requested_by: Mapped[UUID] = mapped_column(Uuid)
    requested_side: Mapped[str] = mapped_column(String(8))
    status: Mapped[str] = mapped_column(String(10))
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    confirmed_by: Mapped[UUID | None] = mapped_column(Uuid)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
