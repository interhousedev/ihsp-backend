"""certificates: the ``standard`` flag and the shared honor category of a type.

Revision ID: certificates_0005
Revises: certificates_0004
Create Date: 2026-11-21 10:00:00.000000

``standard`` marks standardised exams (SAT, IELTS, ...): admission lists them with the
test scores instead of suggesting them as honors. ``category`` is one of the shared
honor categories. Types are matched by their stable code. Downgrade drops both columns.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "certificates_0005"
down_revision: str | Sequence[str] | None = "certificates_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STANDARD = (
    "sat",
    "act",
    "ielts",
    "toefl",
    "duolingo",
    "cefr",
    "national",
    "ap",
    "german",
    "japanese",
    "french",
)
CATEGORY = {
    "olympiad": "olympiad",
    "volunteering": "leadership",
    "other": "other",
    **dict.fromkeys(STANDARD, "academic"),
}


def upgrade() -> None:
    """Add the columns; flag the built-in standard exams and give categories."""
    op.add_column(
        "types",
        sa.Column(
            "standard", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        schema="certificates",
    )
    op.add_column(
        "types",
        sa.Column("category", sa.String(length=24), nullable=True),
        schema="certificates",
    )
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "UPDATE certificates.types SET standard = true WHERE code = ANY(:codes)"
        ),
        {"codes": list(STANDARD)},
    )
    for code, category in CATEGORY.items():
        bind.execute(
            sa.text("UPDATE certificates.types SET category = :c WHERE code = :code"),
            {"c": category, "code": code},
        )


def downgrade() -> None:
    """Drop the columns."""
    op.drop_column("types", "category", schema="certificates")
    op.drop_column("types", "standard", schema="certificates")
