"""admission timestamps: created_at and updated_at on every table.

Revision ID: admission_0006
Revises: admission_0005
Create Date: 2026-11-19 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "admission_0006"
down_revision: str | Sequence[str] | None = "admission_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Tables of the first migrations and the timestamp columns each one lacked.
MISSING: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("admission_stats", ("created_at", "updated_at")),
    ("affordability_checks", ("created_at", "updated_at")),
    ("aid_policies", ("created_at", "updated_at")),
    ("audit_events", ("created_at", "updated_at")),
    ("campuses", ("created_at", "updated_at")),
    ("catalog_proposals", ("updated_at",)),
    ("checklist_items", ("created_at", "updated_at")),
    ("comments", ("updated_at",)),
    ("costs_of_attendance", ("created_at", "updated_at")),
    ("courses", ("updated_at",)),
    ("deadlines", ("created_at", "updated_at")),
    ("deck_decisions", ("created_at", "updated_at")),
    ("document_attachments", ("created_at", "updated_at")),
    ("document_versions", ("created_at", "updated_at")),
    ("documents", ("updated_at",)),
    ("eligibility_rules", ("created_at", "updated_at")),
    ("entitlements", ("created_at", "updated_at")),
    ("essay_versions", ("updated_at",)),
    ("essays", ("created_at",)),
    ("facts", ("created_at", "updated_at")),
    ("goal_milestones", ("created_at", "updated_at")),
    ("guest_links", ("updated_at",)),
    ("guest_sessions", ("updated_at",)),
    ("help_responses", ("updated_at",)),
    ("institutions", ("updated_at",)),
    ("item_interviews", ("updated_at",)),
    ("item_metrics", ("created_at", "updated_at")),
    ("list_entries", ("created_at", "updated_at")),
    ("milestones", ("created_at", "updated_at")),
    ("officer_settings", ("created_at",)),
    ("places", ("created_at", "updated_at")),
    ("preferences", ("updated_at",)),
    ("profile_words", ("created_at",)),
    ("profile_words_history", ("created_at", "updated_at")),
    ("profiles", ("created_at",)),
    ("programs", ("created_at", "updated_at")),
    ("proof_claims", ("created_at", "updated_at")),
    ("proofs", ("created_at", "updated_at")),
    ("reminder_prefs", ("created_at", "updated_at")),
    ("reminders", ("created_at", "updated_at")),
    ("requirements", ("created_at", "updated_at")),
    ("review_feedback", ("updated_at",)),
    ("reviews", ("updated_at",)),
    ("routes", ("created_at", "updated_at")),
    ("runtime_settings", ("created_at",)),
    ("safety_facts", ("created_at", "updated_at")),
    ("scholarships", ("created_at", "updated_at")),
    ("sources", ("created_at", "updated_at")),
    ("staff_assignments", ("created_at", "updated_at")),
    ("staff_roles", ("updated_at",)),
    ("staff_saved_views", ("updated_at",)),
    ("transcript_requests", ("created_at", "updated_at")),
)


def upgrade() -> None:
    """Add the missing timestamps; existing rows get the migration time."""
    for table, columns in MISSING:
        for column in columns:
            op.add_column(
                table,
                sa.Column(
                    column,
                    sa.DateTime(timezone=True),
                    server_default=sa.text("now()"),
                    nullable=False,
                ),
                schema="admission",
            )


def downgrade() -> None:
    """Drop the columns again."""
    for table, columns in reversed(MISSING):
        for column in reversed(columns):
            op.drop_column(table, column, schema="admission")
