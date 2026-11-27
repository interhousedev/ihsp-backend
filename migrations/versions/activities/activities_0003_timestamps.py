"""Give every activities table created_at and updated_at.

Revision ID: activities_0003
Revises: activities_0002
Create Date: 2026-11-27 14:10:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "activities_0003"
down_revision: str | Sequence[str] | None = "activities_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = (
    "activities.activities_clubs",
    "activities.activities_declarations",
    "activities.activities_memberships",
    "activities.activities_transfers",
    "activities.activities_events",
    "activities.activities_rsvps",
    "activities.activities_event_reports",
    "activities.activities_ratings",
    "activities.activities_announcements",
    "activities.activities_contact_messages",
    "activities.activities_planner_items",
    "activities.activities_draft_rounds",
    "activities.activities_draft_signups",
    "activities.activities_draft_picks",
    "activities.activities_club_profiles",
    "activities.activities_points_ledger",
    "activities.activities_points_optout",
    "activities.activities_positions",
    "activities.activities_position_applications",
    "activities.activities_team_seats",
    "activities.activities_consent_events",
    "activities.activities_club_courses",
)


def upgrade() -> None:
    """Add the missing created_at / updated_at columns."""
    for table in _TABLES:
        for column in ("created_at", "updated_at"):
            op.execute(
                f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} "
                "TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()"
            )


def downgrade() -> None:
    """Drop the updated_at columns (created_at may predate this revision)."""
    for table in _TABLES:
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS updated_at")
