"""Course settings: profile, landing page, audience, enrolment window, link report.

Revision ID: lms_0003
Revises: lms_0002
Create Date: 2026-10-17 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "lms_0003"
down_revision: str | Sequence[str] | None = "lms_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON_EMPTY = sa.text("'[]'::jsonb")


def upgrade() -> None:
    """Add the settings columns and backfill ``publish_state``."""
    add = lambda column: op.add_column("courses", column, schema="lms")  # noqa: E731
    add(sa.Column("code", sa.String(32)))
    add(sa.Column("friendly_name", sa.String(255)))
    add(sa.Column("summary", sa.String(500), server_default=sa.text("''")))
    add(sa.Column("banner_file_id", sa.Uuid()))
    add(sa.Column("accent_color", sa.String(7)))
    add(sa.Column("language", sa.String(8), server_default=sa.text("'ru'")))
    add(sa.Column("level", sa.String(16)))
    add(sa.Column("workload_hours_per_week", sa.Integer()))
    add(sa.Column("duration_weeks", sa.Integer()))
    for name in ("tags", "outcomes", "requirements", "audience"):
        add(sa.Column(name, postgresql.JSONB(), server_default=JSON_EMPTY))
    add(sa.Column("audience_scope", sa.String(16), server_default=sa.text("'link'")))
    add(sa.Column("audience_group_ids", postgresql.JSONB(), server_default=JSON_EMPTY))
    add(sa.Column("enrolment_open", sa.Boolean(), server_default=sa.text("true")))
    add(sa.Column("enrolment_starts_at", sa.DateTime(timezone=True)))
    add(sa.Column("enrolment_ends_at", sa.DateTime(timezone=True)))
    add(sa.Column("navigation", postgresql.JSONB(), server_default=JSON_EMPTY))
    add(sa.Column("publish_state", sa.String(16), server_default=sa.text("'draft'")))
    add(sa.Column("link_report", postgresql.JSONB()))
    op.execute(
        "UPDATE lms.courses SET publish_state = CASE "
        "WHEN status = 'archived' THEN 'archived' "
        "WHEN live_version_id IS NOT NULL THEN 'published' ELSE 'draft' END"
    )
    for name in ("summary", "language", "audience_scope", "publish_state"):
        op.alter_column("courses", name, nullable=False, schema="lms")
    for name in (
        "tags",
        "outcomes",
        "requirements",
        "audience",
        "audience_group_ids",
        "enrolment_open",
        "navigation",
    ):
        op.alter_column("courses", name, nullable=False, schema="lms")


def downgrade() -> None:
    """Drop the settings columns."""
    for name in (
        "link_report",
        "publish_state",
        "navigation",
        "enrolment_ends_at",
        "enrolment_starts_at",
        "enrolment_open",
        "audience_group_ids",
        "audience_scope",
        "audience",
        "requirements",
        "outcomes",
        "tags",
        "duration_weeks",
        "workload_hours_per_week",
        "level",
        "language",
        "accent_color",
        "banner_file_id",
        "summary",
        "friendly_name",
        "code",
    ):
        op.drop_column("courses", name, schema="lms")
