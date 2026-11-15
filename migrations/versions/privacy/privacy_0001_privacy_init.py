"""privacy init: erasure requests and data exports.

Revision ID: privacy_0001
Revises:
Create Date: 2026-11-16 10:00:00.000000

Users are identity users (no cross-schema foreign key). One open erasure request
(``pending_review`` or ``approved``) per user is enforced by a partial unique index.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "privacy_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = ("privacy",)
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the schema and the tables."""
    op.execute("CREATE SCHEMA IF NOT EXISTS privacy")
    op.execute("""
        CREATE TABLE privacy.erasure_requests (
            id uuid NOT NULL,
            user_id uuid NOT NULL,
            status text NOT NULL,
            requested_at timestamptz NOT NULL,
            decided_at timestamptz,
            decided_by uuid,
            reject_reason text,
            closes_on date,
            completed_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT pk_erasure_requests PRIMARY KEY (id)
        )
        """)
    op.execute(
        "CREATE UNIQUE INDEX uq_erasure_requests_open ON privacy.erasure_requests "
        "(user_id) WHERE status IN ('pending_review', 'approved')"
    )
    op.execute(
        "CREATE INDEX ix_erasure_requests_status ON privacy.erasure_requests "
        "(status, requested_at)"
    )
    op.execute(
        "CREATE INDEX ix_erasure_requests_user_id ON privacy.erasure_requests (user_id)"
    )
    op.execute("""
        CREATE TABLE privacy.exports (
            id uuid NOT NULL,
            user_id uuid NOT NULL,
            status text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            finished_at timestamptz,
            expires_at timestamptz,
            storage_key text,
            byte_size bigint,
            error text,
            CONSTRAINT pk_exports PRIMARY KEY (id)
        )
        """)
    op.execute(
        "CREATE INDEX ix_exports_user_id ON privacy.exports (user_id, created_at)"
    )


def downgrade() -> None:
    """Drop the schema."""
    op.execute("DROP SCHEMA IF EXISTS privacy CASCADE")
