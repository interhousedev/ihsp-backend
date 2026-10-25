"""Teacher temporary marks notification type.

Revision ID: notify_0013
Revises: notify_0012
Create Date: 2026-10-20 15:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "notify_0013"
down_revision: str | Sequence[str] | None = "notify_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_TYPES = (
    "marks",
    "result_drop",
    "result_below",
    "lesson_resources",
    "lesson_prompt",
    "lesson_changed",
    "mail",
    "mail_bounced",
    "broadcast",
    "emis_reauth",
    "files_expiring",
    "telegram_linked",
    "otp_reset_requested",
    "login_failures",
    "account_closing",
    "mail_suspended",
    "sync_alert",
    "notebook_artifact_ready",
    "assessment_reminder",
    "library_item_approved",
    "library_item_changes_requested",
    "library_item_rejected",
    "library_item_unpublished",
    "library_queue_waiting",
    "library_report_filed",
    "library_reading_list_new",
    "curator_exam_mark",
    "library_suggestion_approved",
    "library_suggestion_declined",
    "student_sync_failed",
    "knowledge_gap",
    "lesson_absence",
    "curator_absences",
)
NEW_TYPES = ("teacher_temporary_marks",)
CONSTRAINT = "ck_notifications_type"


def _replace_constraint(types: tuple[str, ...]) -> None:
    """Re-create the CHECK constraint of ``type``."""
    op.execute(f"ALTER TABLE notify.notifications DROP CONSTRAINT {CONSTRAINT}")
    values = ", ".join(f"'{value}'" for value in types)
    op.execute(
        f"ALTER TABLE notify.notifications "
        f"ADD CONSTRAINT {CONSTRAINT} CHECK (type IN ({values}))"
    )


def upgrade() -> None:
    """Allow ``teacher_temporary_marks``."""
    _replace_constraint((*OLD_TYPES, *NEW_TYPES))


def downgrade() -> None:
    """Forbid the types again; their rows are deleted."""
    values = ", ".join(f"'{value}'" for value in NEW_TYPES)
    op.execute(f"DELETE FROM notify.notifications WHERE type IN ({values})")
    _replace_constraint(OLD_TYPES)
