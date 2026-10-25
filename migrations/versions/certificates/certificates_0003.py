"""certificates: level, score, percent, subject, year and serial become custom fields.

Revision ID: certificates_0003
Revises: certificates_0002
Create Date: 2026-10-18 12:00:00.000000

Each type gets custom field definitions from its old ``asks_*`` flags (level: a
single choice of its levels, or text; score and year: numbers with their bounds;
percent: a number 0-100; subject: text), and every type gets ``serial`` (text), since
the serial identifies an entry for the EMIS import. The entries' column values are
copied into ``custom_values`` under the same keys, the serial's unique index moves to
the jsonb key, and the old columns are dropped.

The downgrade restores the columns and the ``asks_*`` flags from the field
definitions, copies the values back, and removes the converted keys from the types'
fields and the entries' values. A field added after the upgrade under one of these keys
is removed by the downgrade.
"""

import json
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "certificates_0003"
down_revision: str | Sequence[str] | None = "certificates_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONVERTED = ("level", "score", "percent", "subject", "year", "serial")
LABELS: dict[str, dict[str, str]] = {
    "level": {"uz": "Daraja", "ru": "Уровень", "en": "Level"},
    "score": {"uz": "Ball", "ru": "Балл", "en": "Score"},
    "percent": {"uz": "Foiz", "ru": "Процент", "en": "Percent"},
    "subject": {"uz": "Fan", "ru": "Предмет", "en": "Subject"},
    "year": {"uz": "Yil", "ru": "Год", "en": "Year"},
    "serial": {"uz": "Seriya raqami", "ru": "Серийный номер", "en": "Serial number"},
}
COLUMNS = {
    "level": "String(40)",
    "score": "Float",
    "percent": "Float",
    "subject": "String(255)",
    "year": "SmallInteger",
    "serial": "String(255)",
}
SERIAL_INDEX = "uq_entries_student_type_serial"


def _field(key: str, kind: str, **extra: Any) -> dict[str, Any]:
    return {
        "key": key,
        "kind": kind,
        "label": dict(LABELS[key]),
        "required": False,
        "options": [],
        "allow_other": False,
        "min": None,
        "max": None,
        **extra,
    }


def _converted_fields(row: dict[str, Any]) -> list[dict[str, Any]]:
    """The custom field definitions a type's old flags stand for."""
    fields: list[dict[str, Any]] = []
    levels = [str(level) for level in json.loads(row["levels"] or "[]")]
    if row["asks_level"]:
        if levels:
            fields.append(_field("level", "single", options=levels))
        else:
            fields.append(_field("level", "text"))
    if row["asks_score"]:
        fields.append(
            _field("score", "number", min=row["score_min"], max=row["score_max"])
        )
    if row["asks_percent"]:
        fields.append(_field("percent", "number", min=0, max=100))
    if row["asks_year"]:
        fields.append(_field("year", "number", min=1990, max=2100))
    if row["asks_subject"]:
        fields.append(_field("subject", "text"))
    fields.append(_field("serial", "text"))
    return fields


def _load_fields(raw: str | None) -> list[dict[str, Any]]:
    return [dict(item) for item in json.loads(raw or "[]")]


def upgrade() -> None:
    """Move the per-type columns into custom fields and custom values."""
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT id, levels::text AS levels, asks_level, asks_score, score_min, "
            "score_max, asks_percent, asks_subject, asks_year, "
            "custom_fields::text AS custom_fields FROM certificates.types"
        )
    ).mappings()
    for row in rows.all():
        kept = [
            item
            for item in _load_fields(row["custom_fields"])
            if item.get("key") not in CONVERTED
        ]
        fields = _converted_fields(dict(row)) + kept
        bind.execute(
            sa.text(
                "UPDATE certificates.types SET custom_fields = CAST(:fields AS jsonb) "
                "WHERE id = :id"
            ),
            {"fields": json.dumps(fields), "id": row["id"]},
        )
    bind.execute(
        sa.text(
            "UPDATE certificates.entries SET custom_values = custom_values || "
            "jsonb_strip_nulls(jsonb_build_object('level', level, 'score', score, "
            "'percent', percent, 'subject', subject, 'year', year, 'serial', serial))"
        )
    )
    op.execute(f"DROP INDEX certificates.{SERIAL_INDEX}")
    op.execute(
        f"CREATE UNIQUE INDEX {SERIAL_INDEX} ON certificates.entries "
        "(student_id, type_id, (custom_values->>'serial')) "
        "WHERE custom_values->>'serial' IS NOT NULL"
    )
    for column in COLUMNS:
        op.drop_column("entries", column, schema="certificates")
    for column in (
        "levels",
        "asks_level",
        "asks_score",
        "score_min",
        "score_max",
        "asks_percent",
        "asks_subject",
        "asks_year",
    ):
        op.drop_column("types", column, schema="certificates")


def downgrade() -> None:
    """Restore the columns and the flags, and copy the values back."""
    op.add_column(
        "types",
        sa.Column(
            "levels",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        schema="certificates",
    )
    for flag, default in (
        ("asks_level", "false"),
        ("asks_score", "false"),
        ("asks_percent", "false"),
        ("asks_subject", "false"),
        ("asks_year", "true"),
    ):
        op.add_column(
            "types",
            sa.Column(
                flag, sa.Boolean(), server_default=sa.text(default), nullable=False
            ),
            schema="certificates",
        )
    op.add_column(
        "types",
        sa.Column("score_min", sa.Float(), nullable=True),
        schema="certificates",
    )
    op.add_column(
        "types",
        sa.Column("score_max", sa.Float(), nullable=True),
        schema="certificates",
    )
    for column, column_type in (
        ("level", sa.String(length=40)),
        ("score", sa.Float()),
        ("percent", sa.Float()),
        ("subject", sa.String(length=255)),
        ("year", sa.SmallInteger()),
        ("serial", sa.String(length=255)),
    ):
        op.add_column(
            "entries",
            sa.Column(column, column_type, nullable=True),
            schema="certificates",
        )

    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT id, custom_fields::text AS custom_fields FROM certificates.types"
        )
    ).mappings()
    for row in rows.all():
        fields = _load_fields(row["custom_fields"])
        by_key = {item.get("key"): item for item in fields}
        level = by_key.get("level")
        score = by_key.get("score")
        levels = (
            [str(o) for o in level.get("options") or []]
            if level is not None and level.get("kind") == "single"
            else []
        )
        bind.execute(
            sa.text(
                "UPDATE certificates.types SET levels = CAST(:levels AS jsonb), "
                "asks_level = :asks_level, asks_score = :asks_score, "
                "score_min = :score_min, score_max = :score_max, "
                "asks_percent = :asks_percent, asks_subject = :asks_subject, "
                "asks_year = :asks_year, custom_fields = CAST(:fields AS jsonb) "
                "WHERE id = :id"
            ),
            {
                "levels": json.dumps(levels),
                "asks_level": level is not None,
                "asks_score": score is not None,
                "score_min": score.get("min") if score else None,
                "score_max": score.get("max") if score else None,
                "asks_percent": "percent" in by_key,
                "asks_subject": "subject" in by_key,
                "asks_year": "year" in by_key,
                "fields": json.dumps(
                    [item for item in fields if item.get("key") not in CONVERTED]
                ),
                "id": row["id"],
            },
        )
    op.execute(
        "UPDATE certificates.entries SET "
        "level = custom_values->>'level', "
        "score = CASE WHEN jsonb_typeof(custom_values->'score') = 'number' "
        "THEN (custom_values->>'score')::float8 END, "
        "percent = CASE WHEN jsonb_typeof(custom_values->'percent') = 'number' "
        "THEN (custom_values->>'percent')::float8 END, "
        "subject = custom_values->>'subject', "
        "year = CASE WHEN jsonb_typeof(custom_values->'year') = 'number' "
        "THEN ROUND((custom_values->>'year')::numeric)::smallint END, "
        "serial = custom_values->>'serial', "
        "custom_values = custom_values - ARRAY["
        + ", ".join(f"'{key}'" for key in CONVERTED)
        + "]"
    )
    op.execute(f"DROP INDEX certificates.{SERIAL_INDEX}")
    op.execute(
        f"CREATE UNIQUE INDEX {SERIAL_INDEX} ON certificates.entries "
        "(student_id, type_id, serial) WHERE serial IS NOT NULL"
    )
