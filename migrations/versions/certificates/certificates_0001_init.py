"""certificates init.

Revision ID: certificates_0001
Revises:
Create Date: 2026-10-17 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from uuid_utils.compat import uuid7

# revision identifiers, used by Alembic.
revision: str = "certificates_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = ("certificates",)
depends_on: str | Sequence[str] | None = None

IELTS = [f"{x / 2:.1f}" for x in range(8, 19)]  # 4.0 .. 9.0 step 0.5
CEFR = ["A1", "A2", "B1", "B2", "C1", "C2"]
NATIONAL = ["A+", "A", "B+", "B", "C+", "C"]
OLYMPIAD = ["School", "Local", "Republican", "National", "International"]
LANGUAGE_LEVELS = ["A1", "A2", "B1", "B2", "C1", "C2"]

# code, (uz, ru, en), levels, asks flags, score range, builtin
SEED: list[dict[str, object]] = [
    {
        "code": "ielts",
        "name": ("IELTS", "IELTS", "IELTS"),
        "levels": IELTS,
        "asks_level": True,
    },
    {
        "code": "cefr",
        "name": ("CEFR sertifikati", "Сертификат CEFR", "CEFR certificate"),
        "levels": CEFR,
        "asks_level": True,
        "asks_score": True,
        "asks_subject": True,
        "builtin": True,
    },
    {
        "code": "sat",
        "name": ("SAT", "SAT", "SAT"),
        "asks_score": True,
        "score_min": 400,
        "score_max": 1600,
    },
    {
        "code": "national",
        "name": (
            "Milliy sertifikat",
            "Национальный сертификат",
            "National certificate",
        ),
        "levels": NATIONAL,
        "asks_level": True,
        "asks_percent": True,
        "asks_score": True,
        "asks_subject": True,
        "builtin": True,
    },
    {
        "code": "volunteering",
        "name": ("Volontyorlik", "Волонтёрство", "Volunteering"),
    },
    {
        "code": "olympiad",
        "name": ("Olimpiada", "Олимпиада", "Olympiad"),
        "levels": OLYMPIAD,
        "asks_level": True,
        "asks_subject": True,
    },
    {
        "code": "ap",
        "name": ("AP (Advanced Placement)", "AP (Advanced Placement)", "AP"),
        "asks_score": True,
        "score_min": 1,
        "score_max": 5,
        "asks_subject": True,
    },
    {
        "code": "german",
        "name": ("Nemis tili", "Немецкий язык", "German"),
        "levels": LANGUAGE_LEVELS,
        "asks_level": True,
    },
    {
        "code": "japanese",
        "name": ("Yapon tili", "Японский язык", "Japanese"),
        "levels": ["N5", "N4", "N3", "N2", "N1"],
        "asks_level": True,
    },
    {
        "code": "french",
        "name": ("Fransuz tili", "Французский язык", "French"),
        "levels": LANGUAGE_LEVELS,
        "asks_level": True,
    },
    {
        "code": "other",
        "name": ("Boshqa", "Другое", "Other"),
    },
]


def _stamps() -> list[sa.Column]:
    return [
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
    ]


def _seed_types() -> None:
    types = sa.table(
        "types",
        sa.column("id", sa.Uuid()),
        sa.column("code", sa.String()),
        sa.column("name", postgresql.JSONB()),
        sa.column("levels", postgresql.JSONB()),
        sa.column("asks_level", sa.Boolean()),
        sa.column("asks_score", sa.Boolean()),
        sa.column("score_min", sa.Float()),
        sa.column("score_max", sa.Float()),
        sa.column("asks_percent", sa.Boolean()),
        sa.column("asks_subject", sa.Boolean()),
        sa.column("asks_year", sa.Boolean()),
        sa.column("builtin", sa.Boolean()),
        sa.column("position", sa.Integer()),
        schema="certificates",
    )
    rows = []
    for position, item in enumerate(SEED):
        uz, ru, en = item["name"]  # type: ignore[misc]
        rows.append(
            {
                "id": uuid7(),
                "code": item["code"],
                "name": {"uz": uz, "ru": ru, "en": en},
                "levels": item.get("levels", []),
                "asks_level": item.get("asks_level", False),
                "asks_score": item.get("asks_score", False),
                "score_min": item.get("score_min"),
                "score_max": item.get("score_max"),
                "asks_percent": item.get("asks_percent", False),
                "asks_subject": item.get("asks_subject", False),
                "asks_year": True,
                "builtin": item.get("builtin", False),
                "position": position,
            }
        )
    op.bulk_insert(types, rows)


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("CREATE SCHEMA IF NOT EXISTS certificates")
    op.create_table(
        "types",
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("name", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "levels",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'"),
            nullable=False,
        ),
        sa.Column(
            "asks_level", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column(
            "asks_score", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("score_min", sa.Float(), nullable=True),
        sa.Column("score_max", sa.Float(), nullable=True),
        sa.Column(
            "asks_percent",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "asks_subject",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "asks_year", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.Column(
            "builtin", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column(
            "position", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        *_stamps(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_types")),
        sa.UniqueConstraint("code", name=op.f("uq_types_code")),
        schema="certificates",
    )
    op.create_table(
        "entries",
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("type_id", sa.Uuid(), nullable=False),
        sa.Column("level", sa.String(length=40), nullable=True),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("percent", sa.Float(), nullable=True),
        sa.Column("subject", sa.String(length=255), nullable=True),
        sa.Column("year", sa.SmallInteger(), nullable=True),
        sa.Column("serial", sa.String(length=255), nullable=True),
        sa.Column(
            "source",
            sa.String(length=10),
            server_default=sa.text("'manual'"),
            nullable=False,
        ),
        sa.Column("issued_at", sa.Date(), nullable=True),
        sa.Column("expires_at", sa.Date(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        *_stamps(),
        sa.ForeignKeyConstraint(
            ["type_id"],
            ["certificates.types.id"],
            name=op.f("fk_entries_type_id_types"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_entries")),
        schema="certificates",
    )
    op.create_index(
        "ix_entries_student_id", "entries", ["student_id"], schema="certificates"
    )
    op.create_index("ix_entries_type_id", "entries", ["type_id"], schema="certificates")
    op.create_index(
        "uq_entries_student_type_serial",
        "entries",
        ["student_id", "type_id", "serial"],
        unique=True,
        schema="certificates",
        postgresql_where=sa.text("serial IS NOT NULL"),
    )
    op.create_table(
        "entry_files",
        sa.Column("file_id", sa.Uuid(), nullable=False),
        sa.Column("entry_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("content_type", sa.String(length=127), nullable=False),
        *_stamps(),
        sa.ForeignKeyConstraint(
            ["entry_id"],
            ["certificates.entries.id"],
            name=op.f("fk_entry_files_entry_id_entries"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("file_id", name=op.f("pk_entry_files")),
        schema="certificates",
    )
    op.create_index(
        "ix_entry_files_entry_id", "entry_files", ["entry_id"], schema="certificates"
    )
    _seed_types()


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "ix_entry_files_entry_id", table_name="entry_files", schema="certificates"
    )
    op.drop_table("entry_files", schema="certificates")
    op.drop_index(
        "uq_entries_student_type_serial", table_name="entries", schema="certificates"
    )
    op.drop_index("ix_entries_type_id", table_name="entries", schema="certificates")
    op.drop_index("ix_entries_student_id", table_name="entries", schema="certificates")
    op.drop_table("entries", schema="certificates")
    op.drop_table("types", schema="certificates")
    op.execute("DROP SCHEMA IF EXISTS certificates")
