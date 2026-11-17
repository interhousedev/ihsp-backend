"""Organizations of opportunities, their comments and the reports on comments."""

from datetime import datetime
from uuid import UUID

from app.modules.admission.domain.opportunity_comments import (
    COMMENT_STATUSES,
    REPORT_STATUSES,
)
from app.modules.admission.domain.orgs import ORG_KINDS
from app.modules.admission.infrastructure.orm._common import (
    CreatedMixin,
    S,
    UpdatedMixin,
    check_in,
)
from app.shared.db.base import Base, IdMixin

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column


class OrgRow(IdMixin, CreatedMixin, UpdatedMixin, Base):
    """A university, company, foundation, government body or NGO."""

    __tablename__ = "orgs"
    __table_args__ = (
        check_in("kind", ORG_KINDS),
        CheckConstraint("logo_url IS NULL OR logo_url LIKE 'https://%'", "logo_https"),
        CheckConstraint("website IS NULL OR website LIKE 'https://%'", "website_https"),
        CheckConstraint("logo_zoom BETWEEN 0.5 AND 3", "logo_zoom_range"),
        S,
    )

    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(12))
    logo_url: Mapped[str | None] = mapped_column(String(2000))
    logo_zoom: Mapped[float] = mapped_column(Float, server_default=text("1"))
    website: Mapped[str | None] = mapped_column(String(2000))
    country: Mapped[str | None] = mapped_column(String(100))


class OppCommentRow(IdMixin, CreatedMixin, UpdatedMixin, Base):
    """A comment under an opportunity."""

    __tablename__ = "opportunity_comments"
    __table_args__ = (
        check_in("status", COMMENT_STATUSES),
        Index("ix_opportunity_comments_opp", "opportunity_id", "created_at"),
        S,
    )

    opportunity_id: Mapped[UUID] = mapped_column(
        ForeignKey("admission.opportunities.id", ondelete="CASCADE")
    )
    author_id: Mapped[UUID] = mapped_column(Uuid)
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(10), server_default=text("'published'"))
    hidden_by: Mapped[UUID | None] = mapped_column(Uuid)
    hidden_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OppCommentReportRow(IdMixin, CreatedMixin, UpdatedMixin, Base):
    """A report of a comment (one per reporter and comment)."""

    __tablename__ = "opportunity_comment_reports"
    __table_args__ = (
        check_in("status", REPORT_STATUSES),
        UniqueConstraint("comment_id", "reporter_id"),
        Index("ix_opp_comment_reports_status", "status", "created_at"),
        S,
    )

    comment_id: Mapped[UUID] = mapped_column(
        ForeignKey("admission.opportunity_comments.id", ondelete="CASCADE")
    )
    reporter_id: Mapped[UUID] = mapped_column(Uuid)
    reason: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(10), server_default=text("'open'"))
    resolved_by: Mapped[UUID | None] = mapped_column(Uuid)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
