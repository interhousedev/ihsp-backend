"""EMIS sync runs can end as ``stopped`` (administrator) or ``paused`` (EMIS asked).

Revision ID: academic_0008
Revises: academic_0007
Create Date: 2026-10-18 12:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "academic_0008"
down_revision: str | Sequence[str] | None = "academic_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD = ("running", "done", "failed")
NEW = ("running", "done", "failed", "stopped", "paused")


def _check(values: tuple[str, ...]) -> str:
    return "status IN (" + ", ".join(f"'{v}'" for v in values) + ")"


def upgrade() -> None:
    """Allow the statuses ``stopped`` and ``paused`` on sync runs."""
    op.drop_constraint(
        op.f("ck_sync_runs_status"), "sync_runs", schema="academic", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_sync_runs_status"), "sync_runs", _check(NEW), schema="academic"
    )


def downgrade() -> None:
    """Back to running, done, failed (stopped and paused runs become failed)."""
    op.execute(
        "UPDATE academic.sync_runs SET status = 'failed' "
        "WHERE status IN ('stopped', 'paused')"
    )
    op.drop_constraint(
        op.f("ck_sync_runs_status"), "sync_runs", schema="academic", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_sync_runs_status"), "sync_runs", _check(OLD), schema="academic"
    )
