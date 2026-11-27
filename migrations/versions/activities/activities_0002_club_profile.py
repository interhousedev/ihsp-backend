"""activities club profile: category, goals, rules, schedule, partners, forms, points.

Revision ID: activities_0002
Revises: activities_0001
Create Date: 2026-11-27 19:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "activities_0002"
down_revision: str | Sequence[str] | None = "activities_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the club profile columns."""
    op.execute("""
ALTER TABLE activities.activities_clubs
	ADD COLUMN category VARCHAR(40) DEFAULT '' NOT NULL,
	ADD COLUMN goals TEXT DEFAULT '' NOT NULL,
	ADD COLUMN rules TEXT DEFAULT '' NOT NULL,
	ADD COLUMN schedule TEXT DEFAULT '' NOT NULL,
	ADD COLUMN partners JSONB DEFAULT '[]'::jsonb NOT NULL,
	ADD COLUMN form_fields JSONB DEFAULT '[]'::jsonb NOT NULL,
	ADD COLUMN points_rules JSONB DEFAULT '{}'::jsonb NOT NULL
""")


def downgrade() -> None:
    """Drop the club profile columns."""
    op.execute("""
ALTER TABLE activities.activities_clubs
	DROP COLUMN category, DROP COLUMN goals, DROP COLUMN rules,
	DROP COLUMN schedule, DROP COLUMN partners, DROP COLUMN form_fields,
	DROP COLUMN points_rules
""")
