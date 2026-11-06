"""certificates: the priority star. SAT's score and IELTS's level are starred.

Revision ID: certificates_0004
Revises: certificates_0003
Create Date: 2026-11-05 10:00:00.000000

Each custom field of a type gets a ``primary`` flag (the priority star: the statistics
group or average by it, one per type). The built-in SAT type stars its ``score`` field
and the built-in IELTS type stars its ``level`` field. Types are matched by their stable
code, never by their name, and a type that does not have the field or already has a
star is left as it is.

The downgrade removes the ``primary`` key from every field.
"""

import json
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "certificates_0004"
down_revision: str | Sequence[str] | None = "certificates_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STARRED_KEYS: dict[str, str] = {"sat": "score", "ielts": "level"}


def starred_fields(code: str, fields: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The type's fields with the star set on the key of its code, if it can be set."""
    key = STARRED_KEYS.get(code)
    if key is None:
        return [dict(item) for item in fields]
    if any(item.get("primary") for item in fields):
        return [dict(item) for item in fields]
    if not any(item.get("key") == key for item in fields):
        return [dict(item) for item in fields]
    return [{**item, "primary": item.get("key") == key} for item in fields]


def upgrade() -> None:
    """Star the SAT score and the IELTS level of the built-in types that have them."""
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT id, code, custom_fields::text AS custom_fields "
            "FROM certificates.types"
        )
    ).mappings()
    for row in rows.all():
        fields = json.loads(row["custom_fields"] or "[]")
        updated = starred_fields(row["code"], fields)
        if updated == fields:
            continue
        bind.execute(
            sa.text(
                "UPDATE certificates.types SET custom_fields = CAST(:fields AS jsonb) "
                "WHERE id = :id"
            ),
            {"fields": json.dumps(updated), "id": row["id"]},
        )


def downgrade() -> None:
    """Remove the star flag from every field of every type."""
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT id, custom_fields::text AS custom_fields FROM certificates.types"
        )
    ).mappings()
    for row in rows.all():
        fields = json.loads(row["custom_fields"] or "[]")
        cleaned = [{k: v for k, v in item.items() if k != "primary"} for item in fields]
        if cleaned == fields:
            continue
        bind.execute(
            sa.text(
                "UPDATE certificates.types SET custom_fields = CAST(:fields AS jsonb) "
                "WHERE id = :id"
            ),
            {"fields": json.dumps(cleaned), "id": row["id"]},
        )
