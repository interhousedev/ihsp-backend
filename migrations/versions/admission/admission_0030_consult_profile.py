"""admission consultations, quiz answers and profile interests.

Revision ID: admission_0030_consult_profile
Revises: admission_0029_mcp
Create Date: 2026-11-20 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "admission_0030_consult_profile"
down_revision: str | Sequence[str] | None = "admission_0029_mcp"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

S = "admission"


def _now() -> sa.TextClause:
    return sa.text("now()")


def upgrade() -> None:
    """Create the three tables."""
    op.create_table(
        "consultations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("with_kind", sa.String(length=10), nullable=False),
        sa.Column("topic", sa.String(length=200), nullable=False),
        sa.Column("details", sa.String(length=1000), server_default="", nullable=False),
        sa.Column(
            "linked_kind", sa.String(length=12), server_default="other", nullable=False
        ),
        sa.Column("linked_id", sa.Uuid(), nullable=True),
        sa.Column(
            "preferred_times",
            postgresql.ARRAY(sa.DateTime(timezone=True)),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("format", sa.String(length=8), nullable=False),
        sa.Column(
            "status", sa.String(length=10), server_default="requested", nullable=False
        ),
        sa.Column("staff_id", sa.Uuid(), nullable=True),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("location", sa.String(length=200), server_default="", nullable=False),
        sa.Column(
            "staff_notes", sa.String(length=2000), server_default="", nullable=False
        ),
        sa.Column(
            "decline_reason", sa.String(length=1000), server_default="", nullable=False
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=_now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=_now(),
            nullable=False,
        ),
        sa.Column(
            "lock_version", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.CheckConstraint(
            "with_kind IN ('counselor', 'mentor')",
            name=op.f("ck_consultations_with_kind"),
        ),
        sa.CheckConstraint(
            "linked_kind IN ('project', 'essay', 'activity', 'application', 'other')",
            name=op.f("ck_consultations_linked_kind"),
        ),
        sa.CheckConstraint(
            "format IN ('online', 'offline')", name=op.f("ck_consultations_format")
        ),
        sa.CheckConstraint(
            "status IN ('requested', 'proposed', 'accepted', 'declined',"
            " 'completed', 'cancelled')",
            name=op.f("ck_consultations_status"),
        ),
        sa.CheckConstraint(
            "cardinality(preferred_times) <= 5",
            name=op.f("ck_consultations_times_count"),
        ),
        sa.CheckConstraint(
            "char_length(topic) <= 200", name=op.f("ck_consultations_topic_length")
        ),
        sa.CheckConstraint(
            "char_length(details) <= 1000", name=op.f("ck_consultations_details_length")
        ),
        sa.CheckConstraint(
            "char_length(location) <= 200",
            name=op.f("ck_consultations_location_length"),
        ),
        sa.CheckConstraint(
            "char_length(staff_notes) <= 2000",
            name=op.f("ck_consultations_staff_notes_length"),
        ),
        sa.CheckConstraint(
            "char_length(decline_reason) <= 1000",
            name=op.f("ck_consultations_decline_reason_length"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_consultations")),
        schema=S,
    )
    op.create_index(
        "ix_consultations_student",
        "consultations",
        ["student_id", "created_at"],
        schema=S,
    )
    op.create_index(
        "ix_consultations_queue", "consultations", ["with_kind", "status"], schema=S
    )
    op.create_index(
        op.f("ix_admission_consultations_staff_id"),
        "consultations",
        ["staff_id"],
        schema=S,
    )

    op.create_table(
        "quiz_answers",
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("quiz", sa.String(length=12), nullable=False),
        sa.Column(
            "answers",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "completed", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=_now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=_now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "quiz IN ('career', 'algorithm')", name=op.f("ck_quiz_answers_quiz")
        ),
        sa.PrimaryKeyConstraint("student_id", "quiz", name=op.f("pk_quiz_answers")),
        schema=S,
    )

    op.create_table(
        "profile_details",
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column(
            "interest_fields",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column(
            "service_interests",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=_now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=_now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "cardinality(interest_fields) <= 19",
            name=op.f("ck_profile_details_interests_count"),
        ),
        sa.CheckConstraint(
            "cardinality(service_interests) <= 8",
            name=op.f("ck_profile_details_services_count"),
        ),
        sa.PrimaryKeyConstraint("student_id", name=op.f("pk_profile_details")),
        schema=S,
    )


def downgrade() -> None:
    """Drop the three tables."""
    op.drop_table("profile_details", schema=S)
    op.drop_table("quiz_answers", schema=S)
    op.drop_index(
        op.f("ix_admission_consultations_staff_id"), "consultations", schema=S
    )
    op.drop_index("ix_consultations_queue", "consultations", schema=S)
    op.drop_index("ix_consultations_student", "consultations", schema=S)
    op.drop_table("consultations", schema=S)
