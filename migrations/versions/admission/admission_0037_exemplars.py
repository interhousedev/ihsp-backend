"""admission exemplar essay library and the counselor permission to curate it.

Revision ID: admission_0037_exemplars
Revises: admission_0036_essay_reviews
Create Date: 2026-11-20 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "admission_0037_exemplars"
down_revision: str | Sequence[str] | None = "admission_0036_essay_reviews"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

S = "admission"
PERMISSION = "exemplars:curate"


def upgrade() -> None:
    """Create exemplar_essays and give counselor_full the curate permission."""
    op.create_table(
        "exemplar_essays",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("institution_id", sa.Uuid(), nullable=True),
        sa.Column(
            "school_name",
            sa.String(length=200),
            server_default=sa.text("''"),
            nullable=False,
        ),
        sa.Column("year", sa.Integer(), nullable=True),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("prompt", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("word_count", sa.Integer(), nullable=False),
        sa.Column("source_url", sa.String(length=500), nullable=False),
        sa.Column(
            "source_name",
            sa.String(length=200),
            server_default=sa.text("''"),
            nullable=False,
        ),
        sa.Column(
            "tags",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("notes", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default=sa.text("'draft'"),
            nullable=False,
        ),
        sa.Column(
            "language",
            sa.String(length=5),
            server_default=sa.text("'en'"),
            nullable=False,
        ),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "lock_version", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.CheckConstraint(
            "kind IN ('personal_statement', 'supplement', 'why_us', 'activity', "
            "'other')",
            name=op.f("ck_exemplar_essays_kind"),
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'published', 'archived')",
            name=op.f("ck_exemplar_essays_status"),
        ),
        sa.CheckConstraint(
            "source_url LIKE 'https://%'",
            name=op.f("ck_exemplar_essays_source_url_https"),
        ),
        sa.CheckConstraint(
            "cardinality(tags) <= 12", name=op.f("ck_exemplar_essays_tags_count")
        ),
        sa.CheckConstraint(
            "word_count >= 0", name=op.f("ck_exemplar_essays_word_count_nonnegative")
        ),
        sa.CheckConstraint(
            "char_length(body) <= 20000", name=op.f("ck_exemplar_essays_body_length")
        ),
        sa.CheckConstraint(
            "char_length(prompt) <= 4000", name=op.f("ck_exemplar_essays_prompt_length")
        ),
        sa.CheckConstraint(
            "char_length(title) <= 200", name=op.f("ck_exemplar_essays_title_length")
        ),
        sa.ForeignKeyConstraint(
            ["institution_id"],
            [f"{S}.institutions.id"],
            name=op.f("fk_exemplar_essays_institution_id_institutions"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_exemplar_essays")),
        schema=S,
    )
    op.create_index(
        "ix_exemplar_essays_status_kind",
        "exemplar_essays",
        ["status", "kind"],
        schema=S,
    )
    op.create_index(
        "ix_exemplar_essays_institution_id",
        "exemplar_essays",
        ["institution_id"],
        schema=S,
    )
    op.create_index(
        "ix_exemplar_essays_source",
        "exemplar_essays",
        ["source_url", "title"],
        schema=S,
    )
    op.execute(
        # nosemgrep: avoid-sqlalchemy-text -- constant schema, bound parameters
        sa.text(
            f"UPDATE {S}.staff_roles SET permissions = "
            "array_append(permissions, :p) WHERE key = 'counselor_full' "
            "AND NOT (:p = ANY(permissions))"
        ).bindparams(p=PERMISSION)
    )


def downgrade() -> None:
    """Take the permission back and drop the table."""
    op.execute(
        # nosemgrep: avoid-sqlalchemy-text -- constant schema, bound parameters
        sa.text(
            f"UPDATE {S}.staff_roles SET permissions = "
            "array_remove(permissions, :p) WHERE key = 'counselor_full'"
        ).bindparams(p=PERMISSION)
    )
    op.drop_index("ix_exemplar_essays_source", "exemplar_essays", schema=S)
    op.drop_index("ix_exemplar_essays_institution_id", "exemplar_essays", schema=S)
    op.drop_index("ix_exemplar_essays_status_kind", "exemplar_essays", schema=S)
    op.drop_table("exemplar_essays", schema=S)
