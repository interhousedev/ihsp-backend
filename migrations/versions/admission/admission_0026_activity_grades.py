"""admission items: AI grade, 60-char titles and Common App categories.

Revision ID: admission_0026_activity_grades
Revises: admission_0025_scholar_orgs
Create Date: 2026-11-17 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "admission_0026_activity_grades"
down_revision: str | Sequence[str] | None = "admission_0025_scholar_orgs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

S = "admission"
_CATEGORIES = (
    "'academic', 'arts', 'athletics', 'leadership_service', 'cultural_global',"
    " 'stem_research', 'other'"
)


def _case() -> str:
    groups = {
        "arts": (
            "Art",
            "Dance",
            "Music: Instrumental",
            "Music: Vocal",
            "Theater/Drama",
            "Journalism/Publication",
        ),
        "athletics": ("Athletics: Club", "Athletics: JV/Varsity"),
        "leadership_service": (
            "Community Service (Volunteer)",
            "Social Justice",
            "Student Govt./Politics",
            "School Spirit",
            "Religious",
            "LGBT",
            "Junior R.O.T.C.",
            "Environmental",
        ),
        "cultural_global": ("Cultural", "Foreign Exchange"),
        "stem_research": (
            "Computer/Technology",
            "Research",
            "Robotics",
            "Science/Math",
        ),
        "academic": ("Academic", "Debate/Speech"),
    }
    whens = " ".join(
        f"WHEN category IN ({', '.join(repr(v) for v in vals)}) THEN '{new}'"
        for new, vals in groups.items()
    )
    return f"CASE {whens} ELSE 'other' END"


_LEGACY_MAP = (
    f"UPDATE admission.items SET category = {_case()}"
    " WHERE kind = 'activity' AND category IS NOT NULL"
    f" AND category NOT IN ({_CATEGORIES})"
)


def upgrade() -> None:
    """Add the grade column, widen titles and map the legacy categories."""
    op.add_column(
        "items", sa.Column("ai_grade", postgresql.JSONB(), nullable=True), schema=S
    )
    op.drop_constraint(op.f("ck_items_position_length"), "items", schema=S)
    op.alter_column(
        "items",
        "position",
        type_=sa.String(60),
        existing_type=sa.String(50),
        schema=S,
    )
    op.create_check_constraint(
        op.f("ck_items_position_length"),
        "items",
        "char_length(position) <= 60",
        schema=S,
    )
    op.execute(
        "UPDATE admission.items SET category = 'regional'"
        " WHERE kind = 'honor' AND category = 'state_regional'"
    )
    op.execute(_LEGACY_MAP)


def downgrade() -> None:
    """Drop the grade column; titles keep their width (data may exceed 50)."""
    op.drop_column("items", "ai_grade", schema=S)
