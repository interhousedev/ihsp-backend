"""onboarding init: progress of the post-registration wizard.

Revision ID: onboarding_0001
Revises:
Create Date: 2026-11-15 10:00:00.000000

Users are identity users (no cross-schema foreign key). No row means nothing was
done, which is also the state of every existing user.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "onboarding_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = ("onboarding",)
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the schema and the table."""
    op.execute("CREATE SCHEMA IF NOT EXISTS onboarding")
    op.execute("""
        CREATE TABLE onboarding.onboarding_progress (
            user_id uuid NOT NULL,
            certificates_prompt_done_at timestamptz,
            completed_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT pk_onboarding_progress PRIMARY KEY (user_id)
        )
        """)


def downgrade() -> None:
    """Drop the schema."""
    op.execute("DROP SCHEMA IF EXISTS onboarding CASCADE")
