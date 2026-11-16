"""legal app scope: documents per app, admission kinds, guardian attestation.

Revision ID: legal_0002
Revises: legal_0001
Create Date: 2026-11-16 10:00:00.000000

A document has an app_scope (``global`` or an app name); versions count per
(kind, app_scope). Acceptances record the scope of the accepted document and
whether a parent or guardian attested it.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "legal_0002"
down_revision: str | Sequence[str] | None = "legal_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

KINDS = (
    "'privacy', 'terms', 'biometric', 'ai', 'admission_privacy', "
    "'admission_terms', 'admission_disclaimer'"
)


def upgrade() -> None:
    """Add the scope and attestation columns and rebuild the keys on them."""
    op.execute("ALTER TABLE legal.documents ALTER COLUMN kind TYPE varchar(32)")
    op.execute(
        "ALTER TABLE legal.documents "
        "ADD COLUMN app_scope varchar(32) NOT NULL DEFAULT 'global'"
    )
    op.execute("ALTER TABLE legal.documents DROP CONSTRAINT ck_documents_kind")
    op.execute(
        f"ALTER TABLE legal.documents ADD CONSTRAINT ck_documents_kind "
        f"CHECK (kind IN ({KINDS}))"
    )
    op.execute("ALTER TABLE legal.documents DROP CONSTRAINT uq_documents_kind_version")
    op.execute(
        "ALTER TABLE legal.documents ADD CONSTRAINT uq_documents_kind_scope_version "
        "UNIQUE (kind, app_scope, version)"
    )
    op.execute("DROP INDEX legal.uq_documents_one_draft_per_kind")
    op.execute(
        "CREATE UNIQUE INDEX uq_documents_one_draft_per_kind_scope "
        "ON legal.documents (kind, app_scope) WHERE status = 'draft'"
    )

    op.execute("ALTER TABLE legal.acceptances ALTER COLUMN kind TYPE varchar(32)")
    op.execute(
        "ALTER TABLE legal.acceptances "
        "ADD COLUMN app_scope varchar(32) NOT NULL DEFAULT 'global'"
    )
    op.execute(
        "ALTER TABLE legal.acceptances "
        "ADD COLUMN guardian_attested boolean NOT NULL DEFAULT false"
    )
    op.execute(
        "ALTER TABLE legal.acceptances DROP CONSTRAINT uq_acceptances_user_kind_version"
    )
    op.execute(
        "ALTER TABLE legal.acceptances "
        "ADD CONSTRAINT uq_acceptances_user_kind_scope_version "
        "UNIQUE (user_id, kind, app_scope, version)"
    )
    op.execute("DROP INDEX legal.ix_acceptances_kind_version")
    op.execute(
        "CREATE INDEX ix_acceptances_kind_scope_version "
        "ON legal.acceptances (kind, app_scope, version)"
    )


def downgrade() -> None:
    """Drop app documents and their acceptances, then the new columns."""
    op.execute("DELETE FROM legal.acceptances WHERE app_scope <> 'global'")
    op.execute("DELETE FROM legal.documents WHERE app_scope <> 'global'")
    op.execute("DELETE FROM legal.acceptances WHERE kind LIKE 'admission\\_%'")
    op.execute("DELETE FROM legal.documents WHERE kind LIKE 'admission\\_%'")
    op.execute("DROP INDEX legal.ix_acceptances_kind_scope_version")
    op.execute(
        "CREATE INDEX ix_acceptances_kind_version "
        "ON legal.acceptances (kind, version)"
    )
    op.execute(
        "ALTER TABLE legal.acceptances "
        "DROP CONSTRAINT uq_acceptances_user_kind_scope_version"
    )
    op.execute(
        "ALTER TABLE legal.acceptances ADD CONSTRAINT "
        "uq_acceptances_user_kind_version UNIQUE (user_id, kind, version)"
    )
    op.execute("ALTER TABLE legal.acceptances DROP COLUMN guardian_attested")
    op.execute("ALTER TABLE legal.acceptances DROP COLUMN app_scope")
    op.execute("ALTER TABLE legal.acceptances ALTER COLUMN kind TYPE varchar(16)")
    op.execute("DROP INDEX legal.uq_documents_one_draft_per_kind_scope")
    op.execute(
        "CREATE UNIQUE INDEX uq_documents_one_draft_per_kind "
        "ON legal.documents (kind) WHERE status = 'draft'"
    )
    op.execute(
        "ALTER TABLE legal.documents DROP CONSTRAINT uq_documents_kind_scope_version"
    )
    op.execute(
        "ALTER TABLE legal.documents "
        "ADD CONSTRAINT uq_documents_kind_version UNIQUE (kind, version)"
    )
    op.execute("ALTER TABLE legal.documents DROP CONSTRAINT ck_documents_kind")
    op.execute(
        "ALTER TABLE legal.documents ADD CONSTRAINT ck_documents_kind "
        "CHECK (kind IN ('privacy', 'terms', 'biometric', 'ai'))"
    )
    op.execute("ALTER TABLE legal.documents DROP COLUMN app_scope")
    op.execute("ALTER TABLE legal.documents ALTER COLUMN kind TYPE varchar(16)")
