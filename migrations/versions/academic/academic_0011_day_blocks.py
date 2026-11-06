"""Lesson blocks per weekday: open Saturday and Sunday, retire the old Saturday rows.

``Term.bells`` already keeps the weekdays of each block, so the Monday to Friday
blocks and the times of existing lessons stay as they are. Saturday and Sunday start
empty. Rows kept from before the lyceum dropped Saturday must not come back now that
a Saturday can be real: their blocks are removed, their entries move to weekday 0
(never read), and their lessons dated from today on are cancelled. Older Saturday
lessons stay hidden by ``WEEKEND_LESSONS_SINCE``.

Revision ID: academic_0011
Revises: academic_0010
Create Date: 2026-11-05 12:00:00.000000

"""

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "academic_0011"
down_revision: str | Sequence[str] | None = "academic_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _check_name() -> str:
    # Called from upgrade/downgrade only: op.f needs the migration context.
    return op.f("ck_timetable_entries_weekday")


def _strip_weekend_bells() -> None:
    conn = op.get_bind()
    rows = conn.execute(sa.text("SELECT id, bells FROM academic.terms")).all()
    for term_id, bells in rows:
        kept = []
        for bell in bells or []:
            days = [day for day in bell["weekdays"] if day < 6]
            if days:
                kept.append({**bell, "weekdays": days})
        if kept != bells:
            conn.execute(
                sa.text(
                    "UPDATE academic.terms SET bells = CAST(:bells AS jsonb) "
                    "WHERE id = :id"
                ),
                {"bells": json.dumps(kept), "id": term_id},
            )


def upgrade() -> None:
    """Allow weekdays 0 to 7 and retire what was kept for Saturday."""
    op.drop_constraint(
        _check_name(), "timetable_entries", schema="academic", type_="check"
    )
    op.create_check_constraint(
        _check_name(), "timetable_entries", "weekday BETWEEN 0 AND 7", schema="academic"
    )
    op.execute("UPDATE academic.timetable_entries SET weekday = 0 WHERE weekday = 6")
    op.execute(
        "UPDATE academic.lessons SET status = 'cancelled' "
        "WHERE status = 'scheduled' AND date >= DATE '2026-11-05' "
        "AND extract(isodow FROM date) = 6"
    )
    _strip_weekend_bells()


def downgrade() -> None:
    """Return retired entries to Saturday; weekend blocks and Sunday entries go."""
    op.execute("UPDATE academic.timetable_entries SET weekday = 6 WHERE weekday = 0")
    op.execute("DELETE FROM academic.timetable_entries WHERE weekday = 7")
    op.drop_constraint(
        _check_name(), "timetable_entries", schema="academic", type_="check"
    )
    op.create_check_constraint(
        _check_name(), "timetable_entries", "weekday BETWEEN 1 AND 6", schema="academic"
    )
    _strip_weekend_bells()
