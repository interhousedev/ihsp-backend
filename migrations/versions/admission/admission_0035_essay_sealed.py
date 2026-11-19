"""admission essay text sealed at rest: the essay columns become bytea blobs.

The blobs are AES-256-GCM under a per-student key kept in Vault (see
`app/modules/admission/infrastructure/essay_crypto.py`). Existing plaintext cannot
be sealed by SQL, so the upgrade deletes every essay (with its versions and
ideas), the essay comments and the essay search chunks. Only development data is
lost: production has no admission schema yet. The downgrade deletes them again.

Revision ID: admission_0035_essay_sealed
Revises: admission_0034_opp_author_null
Create Date: 2026-11-19 10:00:00.000000
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "admission_0035_essay_sealed"
down_revision: str | Sequence[str] | None = "admission_0034_opp_author_null"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

S = "admission"
_BLOB = "NULL::bytea"

_COLUMNS: tuple[tuple[str, str, Any, bool, str | None], ...] = (
    ("essays", "title", sa.String(length=120), False, "''"),
    ("essays", "body", sa.Text(), False, "''"),
    ("essays", "notes", sa.Text(), False, "''"),
    ("essays", "plan", postgresql.JSONB(astext_type=sa.Text()), False, "'[]'"),
    ("essay_versions", "name", sa.String(length=60), True, None),
    ("essay_versions", "body", sa.Text(), False, None),
    ("essay_ideas", "body", sa.Text(), False, None),
    ("essay_ideas", "tags", postgresql.ARRAY(sa.Text()), False, "'{}'"),
)
"""Table, column, plaintext type, nullable, plaintext server default."""

_CHECKS: tuple[tuple[str, str, str], ...] = (
    ("essay_versions", "ck_essay_versions_name_length", "char_length(name) <= 60"),
    ("essay_ideas", "ck_essay_ideas_body_length", "char_length(body) <= 1000"),
)
"""Length checks that cannot apply to ciphertext (the domain enforces them)."""


def _clear() -> None:
    """Delete the essay text, its comments and its search chunks."""
    op.execute(f"DELETE FROM {S}.admission_student_chunks WHERE source = 'essay'")
    op.execute(f"DELETE FROM {S}.comments WHERE target_kind = 'essay'")
    op.execute(f"DELETE FROM {S}.essay_ideas")
    op.execute(f"DELETE FROM {S}.essay_versions")
    op.execute(f"DELETE FROM {S}.essays")


def upgrade() -> None:
    """Turn the essay text columns into sealed blobs."""
    _clear()
    for table, name, _ in _CHECKS:
        op.drop_constraint(op.f(name), table, type_="check", schema=S)
    for table, column, kind, nullable, default in _COLUMNS:
        if default:
            op.alter_column(table, column, server_default=None, schema=S)
        op.alter_column(
            table,
            column,
            existing_type=kind,
            type_=sa.LargeBinary(),
            existing_nullable=nullable,
            postgresql_using=_BLOB,
            schema=S,
        )


def downgrade() -> None:
    """Restore the plaintext columns; the sealed essays are deleted."""
    _clear()
    for table, column, kind, nullable, default in _COLUMNS:
        op.alter_column(
            table,
            column,
            existing_type=sa.LargeBinary(),
            type_=kind,
            existing_nullable=nullable,
            postgresql_using=f"NULL::{kind.compile(dialect=postgresql.dialect())}",
            schema=S,
        )
        if default:
            op.alter_column(table, column, server_default=sa.text(default), schema=S)
    for table, name, check in _CHECKS:
        op.create_check_constraint(op.f(name), table, check, schema=S)
