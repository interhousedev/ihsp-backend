"""admission_0047: the term a saved opportunity is placed in.

Revision ID: admission_0047_plan_term
Revises: admission_0046_aid_profile
Create Date: 2026-11-21 15:00:00.000000

``opportunity_plan_entries.planned_term`` (``fall``, ``spring`` or ``summer``) pairs
with ``planned_grade``: the saved plan is a grade-by-term board. Null keeps the old
behaviour (the term of the entry's next dated event). The new catalog fields
(hours per week, start date) live in the entry's JSON payload and need no column;
the migration only fills the figures known for the seeded entries (approximate
weekly hours, and the cost to take them: 0 means free to learn, a paid
certificate is not counted). Rows an administrator already filled stay untouched.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "admission_0047_plan_term"
down_revision: str | None = "admission_0046_aid_profile"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

S = "admission"
T = "opportunity_plan_entries"

# title -> (hours per week, cost in USD to take it)
_KNOWN: dict[str, tuple[float | None, int | None]] = {
    "CS50x: Introduction to Computer Science": (10, 0),
    "CS50's Introduction to Artificial Intelligence with Python": (10, 0),
    "Elements of AI": (5, 0),
    "Full Stack Open": (15, 0),
    "Python Programming MOOC": (8, 0),
    "MIT OpenCourseWare: Linear Algebra (18.06)": (8, 0),
    ("MITx 6.00.1x: Introduction to Computer Science and Programming Using Python"): (
        8,
        0,
    ),
    "Machine Learning Specialization": (6, 0),
    "Financial Markets": (4, 0),
    "Learning How to Learn": (3, 0),
    "ASU Universal Learner Courses": (5, 0),
    "AWS Certified Cloud Practitioner": (6, 100),
    "Cambridge C1 Advanced": (6, 250),
    "Duolingo English Test": (2, 70),
    "TOEFL iBT": (6, 220),
    "Google Career Certificates": (10, 49),
    "International Mathematical Olympiad": (None, 0),
    "International Olympiad in Informatics": (None, 0),
    "NASA International Space Apps Challenge": (None, 0),
    "Technovation Girls": (3, 0),
    "Beamline for Schools": (None, 0),
}


def upgrade() -> None:
    """Add `planned_term` and fill the known hours and costs."""
    op.add_column(T, sa.Column("planned_term", sa.String(10), nullable=True), schema=S)
    op.create_check_constraint(
        op.f("ck_opportunity_plan_entries_planned_term"),
        T,
        "planned_term IN ('fall', 'spring', 'summer')",
        schema=S,
    )
    bind = op.get_bind()
    for title, (hours, cost) in _KNOWN.items():
        bind.execute(
            sa.text(
                "UPDATE admission.opportunities SET payload = payload"
                " || jsonb_strip_nulls(jsonb_build_object("
                "'hours_per_week', CAST(:hours AS numeric),"
                " 'tuition_usd', CASE WHEN payload->>'tuition_usd' IS NULL"
                " THEN CAST(:cost AS integer) END))"
                " WHERE title = :title AND payload->>'hours_per_week' IS NULL"
            ),
            {"title": title, "hours": hours, "cost": cost},
        )


def downgrade() -> None:
    """Drop `planned_term`; the filled figures stay."""
    op.drop_constraint(
        op.f("ck_opportunity_plan_entries_planned_term"), T, schema=S, type_="check"
    )
    op.drop_column(T, "planned_term", schema=S)
