"""admission_0046: how an institution's aid meets need, with its composition.

Revision ID: admission_0046_aid_profile
Revises: admission_0045_honor_categories
Create Date: 2026-11-21 12:00:00.000000

``aid_policies.avg_intl_award`` (never filled) becomes ``avg_aid``, the average
financial aid package in USD, and ``avg_aid_scope`` says whose average it is
(``intl`` for international students, ``overall`` when the institution publishes
no international figure). ``grant_pct``, ``loan_pct`` and ``work_pct`` split that
package into grants, student loans and work-study (each 0-100). Every value stays
null when no official source gives it; the row's source and cycle cite them.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "admission_0046_aid_profile"
down_revision: str | None = "admission_0045_honor_categories"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

S = "admission"
T = "aid_policies"
PCTS = ("grant_pct", "loan_pct", "work_pct")


def upgrade() -> None:
    """Rename the average, add its scope and the composition."""
    op.drop_constraint(
        op.f("ck_quiz_answers_quiz"), "quiz_answers", schema=S, type_="check"
    )
    op.create_check_constraint(
        op.f("ck_quiz_answers_quiz"),
        "quiz_answers",
        "quiz IN ('career', 'algorithm', 'budget')",
        schema=S,
    )
    op.alter_column(T, "avg_intl_award", new_column_name="avg_aid", schema=S)
    op.add_column(T, sa.Column("avg_aid_scope", sa.String(8), nullable=True), schema=S)
    for name in PCTS:
        op.add_column(T, sa.Column(name, sa.SmallInteger(), nullable=True), schema=S)
    op.create_check_constraint(
        op.f("ck_aid_policies_avg_aid_scope"),
        T,
        "avg_aid_scope IN ('intl', 'overall')",
        schema=S,
    )
    for name in PCTS:
        op.create_check_constraint(
            op.f(f"ck_aid_policies_{name}"),
            T,
            f"{name} BETWEEN 0 AND 100",
            schema=S,
        )


def downgrade() -> None:
    """Undo."""
    for name in PCTS:
        op.drop_constraint(op.f(f"ck_aid_policies_{name}"), T, schema=S, type_="check")
    op.drop_constraint(
        op.f("ck_aid_policies_avg_aid_scope"), T, schema=S, type_="check"
    )
    for name in PCTS:
        op.drop_column(T, name, schema=S)
    op.drop_column(T, "avg_aid_scope", schema=S)
    op.alter_column(T, "avg_aid", new_column_name="avg_intl_award", schema=S)
    op.execute("DELETE FROM admission.quiz_answers WHERE quiz = 'budget'")
    op.drop_constraint(
        op.f("ck_quiz_answers_quiz"), "quiz_answers", schema=S, type_="check"
    )
    op.create_check_constraint(
        op.f("ck_quiz_answers_quiz"),
        "quiz_answers",
        "quiz IN ('career', 'algorithm')",
        schema=S,
    )
