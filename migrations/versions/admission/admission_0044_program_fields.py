"""admission_0044: programs carry a school, a master or other degree and field ids.

Revision ID: admission_0044_program_fields
Revises: admission_0043_supp_limits
Create Date: 2026-11-19 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "admission_0044_program_fields"
down_revision: str | None = "admission_0043_supp_limits"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

S = "admission"
TABLE = "programs"


def upgrade() -> None:
    op.drop_constraint(op.f("ck_programs_level"), TABLE, schema=S, type_="check")
    op.create_check_constraint(
        op.f("ck_programs_level"),
        TABLE,
        "level IN ('bachelor', 'master', 'foundation', 'other', '2plus2')",
        schema=S,
    )
    op.add_column(TABLE, sa.Column("school", sa.String(120), nullable=True), schema=S)
    op.add_column(
        TABLE,
        sa.Column(
            "field_ids",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        schema=S,
    )
    op.create_check_constraint(
        op.f("ck_programs_school_length"),
        TABLE,
        "char_length(school) <= 120",
        schema=S,
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_programs_school_length"), TABLE, schema=S, type_="check"
    )
    op.drop_column(TABLE, "field_ids", schema=S)
    op.drop_column(TABLE, "school", schema=S)
    op.drop_constraint(op.f("ck_programs_level"), TABLE, schema=S, type_="check")
    op.create_check_constraint(
        op.f("ck_programs_level"),
        TABLE,
        "level IN ('bachelor', 'foundation', '2plus2')",
        schema=S,
    )
