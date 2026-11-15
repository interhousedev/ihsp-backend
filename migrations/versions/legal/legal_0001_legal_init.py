"""legal init: versioned legal documents and users' acceptances.

Revision ID: legal_0001
Revises:
Create Date: 2026-11-02 10:00:00.000000

No cross-schema foreign keys: user_id and published_by are identity user ids.
Acceptances are append-only: the application only inserts them.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "legal_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = ("legal",)
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the schema, the tables and their indexes."""
    op.execute("CREATE SCHEMA IF NOT EXISTS legal")
    op.execute("""
        CREATE TABLE legal.documents (
            id uuid NOT NULL,
            kind varchar(16) NOT NULL,
            version integer NOT NULL,
            status varchar(16) NOT NULL,
            title jsonb NOT NULL,
            body_markdown jsonb NOT NULL,
            announcement jsonb,
            published_at timestamptz,
            published_by uuid,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT pk_documents PRIMARY KEY (id),
            CONSTRAINT ck_documents_kind CHECK (kind IN ('privacy', 'terms',
                'biometric', 'ai')),
            CONSTRAINT ck_documents_status CHECK (status IN ('draft',
                'published')),
            CONSTRAINT uq_documents_kind_version UNIQUE (kind, version)
        )
        """)
    op.execute(
        "CREATE UNIQUE INDEX uq_documents_one_draft_per_kind "
        "ON legal.documents (kind) WHERE status = 'draft'"
    )
    op.execute("""
        CREATE TABLE legal.acceptances (
            id uuid NOT NULL,
            user_id uuid NOT NULL,
            kind varchar(16) NOT NULL,
            version integer NOT NULL,
            accepted_at timestamptz NOT NULL DEFAULT now(),
            ip text,
            user_agent text,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT pk_acceptances PRIMARY KEY (id),
            CONSTRAINT uq_acceptances_user_kind_version
                UNIQUE (user_id, kind, version)
        )
        """)
    op.execute(
        "CREATE INDEX ix_acceptances_kind_version "
        "ON legal.acceptances (kind, version)"
    )


def downgrade() -> None:
    """Drop the schema with its tables."""
    op.execute("DROP SCHEMA legal CASCADE")
