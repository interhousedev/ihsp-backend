"""legal purpose consents: the admission purposes a subject grants or withdraws.

Revision ID: legal_0003
Revises: legal_0002
Create Date: 2026-11-17 10:00:00.000000

One row per user and purpose (`admission_staff_view`, `admission_ai`,
`admission_sharing`, `admission_finance`); withdrawing sets `withdrawn_at`.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "legal_0003"
down_revision: str | Sequence[str] | None = "legal_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the purpose consent table."""
    op.execute("""
        CREATE TABLE legal.purpose_consents (
            id uuid NOT NULL,
            user_id uuid NOT NULL,
            purpose varchar(32) NOT NULL,
            method varchar(10) NOT NULL DEFAULT 'app',
            given_at timestamptz NOT NULL,
            withdrawn_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT pk_purpose_consents PRIMARY KEY (id),
            CONSTRAINT uq_purpose_consents_user UNIQUE (user_id, purpose),
            CONSTRAINT ck_purpose_consents_method
                CHECK (method IN ('app', 'guardian'))
        )
        """)


def downgrade() -> None:
    """Drop the table."""
    op.execute("DROP TABLE legal.purpose_consents")
