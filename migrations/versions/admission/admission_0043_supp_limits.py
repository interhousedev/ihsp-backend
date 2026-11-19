"""admission_0043: supplement prompt limit unit, minimum and choice group.

Revision ID: admission_0043_supp_limits
Revises: admission_0042_test_sat_erw
Create Date: 2026-11-19 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "admission_0043_supp_limits"
down_revision: str | None = "admission_0042_test_sat_erw"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

S = "admission"
TABLE = "supp_prompts"


def upgrade() -> None:
    op.add_column(
        TABLE,
        sa.Column("limit_unit", sa.String(10), nullable=False, server_default="words"),
        schema=S,
    )
    op.add_column(TABLE, sa.Column("limit_min", sa.Integer(), nullable=True), schema=S)
    op.add_column(
        TABLE, sa.Column("choice_group", sa.String(40), nullable=True), schema=S
    )
    op.drop_constraint("word_limit_range", TABLE, schema=S, type_="check")
    op.create_check_constraint(
        "word_limit_range",
        TABLE,
        "word_limit IS NULL OR (limit_unit = 'words' "
        "AND word_limit BETWEEN 1 AND 5000)"
        " OR (limit_unit = 'characters' AND word_limit BETWEEN 1 AND 30000)",
        schema=S,
    )
    op.create_check_constraint(
        "limit_unit_values",
        TABLE,
        "limit_unit IN ('words', 'characters')",
        schema=S,
    )
    op.create_check_constraint(
        "limit_min_range",
        TABLE,
        "limit_min IS NULL OR (word_limit IS NOT NULL"
        " AND limit_min BETWEEN 1 AND word_limit)",
        schema=S,
    )
    op.create_check_constraint(
        "choice_group_length",
        TABLE,
        "choice_group IS NULL OR char_length(choice_group) BETWEEN 1 AND 40",
        schema=S,
    )


def downgrade() -> None:
    op.drop_constraint("choice_group_length", TABLE, schema=S, type_="check")
    op.drop_constraint("limit_min_range", TABLE, schema=S, type_="check")
    op.drop_constraint("limit_unit_values", TABLE, schema=S, type_="check")
    op.drop_constraint("word_limit_range", TABLE, schema=S, type_="check")
    op.create_check_constraint(
        "word_limit_range",
        TABLE,
        "word_limit IS NULL OR word_limit BETWEEN 1 AND 5000",
        schema=S,
    )
    op.drop_column(TABLE, "choice_group", schema=S)
    op.drop_column(TABLE, "limit_min", schema=S)
    op.drop_column(TABLE, "limit_unit", schema=S)
