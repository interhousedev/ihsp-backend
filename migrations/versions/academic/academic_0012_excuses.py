"""Excuses: templates, excuses and their message threads.

Revision ID: academic_0012
Revises: academic_0011
Create Date: 2026-11-10 12:00:00.000000

"""

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "academic_0012"
down_revision: str | Sequence[str] | None = "academic_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EMPTY = sa.text("'{}'::uuid[]")
NOW = sa.text("now()")

# code, uz, ru, en, requires a document
TEMPLATES = [
    ("illness", "Kasallik", "Болезнь", "Illness", True),
    ("volunteering", "Volontyorlik", "Волонтёрство", "Volunteering", False),
    ("olympiad", "Olimpiada", "Олимпиада", "Olympiad", True),
    ("family", "Oilaviy sabab", "Семейные обстоятельства", "Family reasons", False),
    ("other", "Boshqa sabab", "Другая причина", "Other", False),
]


def upgrade() -> None:
    """Create the excuse tables and seed the reason templates."""
    op.create_table(
        "excuse_templates",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("title", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("requires_document", sa.Boolean(), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("sort", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=NOW,
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=NOW,
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_excuse_templates")),
        sa.UniqueConstraint("code", name=op.f("uq_excuse_templates_code")),
        schema="academic",
    )
    op.create_table(
        "excuses",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("origin", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("template_id", sa.Uuid(), nullable=False),
        sa.Column("reason", sa.Text(), server_default="", nullable=False),
        sa.Column("starts_on", sa.Date(), nullable=False),
        sa.Column("ends_on", sa.Date(), nullable=True),
        sa.Column(
            "lesson_ids",
            postgresql.ARRAY(sa.Uuid()),
            server_default=EMPTY,
            nullable=False,
        ),
        sa.Column(
            "subject_ids",
            postgresql.ARRAY(sa.Uuid()),
            server_default=EMPTY,
            nullable=False,
        ),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("decided_by", sa.Uuid(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_comment", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=NOW,
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=NOW,
            nullable=False,
        ),
        sa.CheckConstraint(
            "origin IN ('request', 'curator')", name=op.f("ck_excuses_origin")
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'cancelled')",
            name=op.f("ck_excuses_status"),
        ),
        sa.CheckConstraint(
            "char_length(reason) <= 2000", name=op.f("ck_excuses_reason_length")
        ),
        sa.CheckConstraint(
            "ends_on IS NULL OR ends_on >= starts_on", name=op.f("ck_excuses_period")
        ),
        sa.ForeignKeyConstraint(
            ["student_id"],
            ["academic.students.user_id"],
            name=op.f("fk_excuses_student_id_students"),
        ),
        sa.ForeignKeyConstraint(
            ["template_id"],
            ["academic.excuse_templates.id"],
            name=op.f("fk_excuses_template_id_excuse_templates"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_excuses")),
        schema="academic",
    )
    op.create_index(
        "ix_excuses_student_id_status",
        "excuses",
        ["student_id", "status"],
        schema="academic",
    )
    op.create_index(
        "ix_excuses_status_created_at",
        "excuses",
        ["status", "created_at"],
        schema="academic",
    )
    op.create_table(
        "excuse_messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("excuse_id", sa.Uuid(), nullable=False),
        sa.Column("author_id", sa.Uuid(), nullable=False),
        sa.Column("body", sa.Text(), server_default="", nullable=False),
        sa.Column(
            "file_ids",
            postgresql.ARRAY(sa.Uuid()),
            server_default=EMPTY,
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=NOW,
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=NOW,
            nullable=False,
        ),
        sa.CheckConstraint(
            "char_length(body) <= 2000", name=op.f("ck_excuse_messages_body_length")
        ),
        sa.ForeignKeyConstraint(
            ["excuse_id"],
            ["academic.excuses.id"],
            name=op.f("fk_excuse_messages_excuse_id_excuses"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_excuse_messages")),
        schema="academic",
    )
    op.create_index(
        "ix_excuse_messages_excuse_id_created_at",
        "excuse_messages",
        ["excuse_id", "created_at"],
        schema="academic",
    )
    conn = op.get_bind()
    for sort, (code, uz, ru, en, document) in enumerate(TEMPLATES):
        conn.execute(
            sa.text(
                "INSERT INTO academic.excuse_templates "
                "(id, code, title, requires_document, active, sort) "
                "VALUES (gen_random_uuid(), :code, CAST(:title AS jsonb), "
                ":document, true, :sort)"
            ),
            {
                "code": code,
                "title": json.dumps({"uz": uz, "ru": ru, "en": en}),
                "document": document,
                "sort": sort,
            },
        )


def downgrade() -> None:
    """Drop the excuse tables."""
    op.drop_index(
        "ix_excuse_messages_excuse_id_created_at",
        table_name="excuse_messages",
        schema="academic",
    )
    op.drop_table("excuse_messages", schema="academic")
    op.drop_index(
        "ix_excuses_status_created_at", table_name="excuses", schema="academic"
    )
    op.drop_index(
        "ix_excuses_student_id_status", table_name="excuses", schema="academic"
    )
    op.drop_table("excuses", schema="academic")
    op.drop_table("excuse_templates", schema="academic")
