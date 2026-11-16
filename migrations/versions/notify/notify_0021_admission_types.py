"""Admission notification types.

Revision ID: notify_0021
Revises: notify_0020
Create Date: 2026-11-16 10:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "notify_0021"
down_revision: str | Sequence[str] | None = "notify_0020"
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
    "teacher_temporary_marks",
    "feedback_new",
    "feedback_response",
    "mcp_scope_offer",
    "gate_unexcused_exit",
    "excuse_requested",
    "excuse_decided",
    "excuse_message",
    "privacy_update",
    "chat_answer_ready",
)
NEW_TYPES = (
    "transcript_requested",
    "transcript_reminder",
    "transcript_ready",
    "transcript_scan_uploaded",
    "transcript_unrouted",
    "admission_document_uploaded",
    "document_attached",
    "document_rejected",
    "admission_deadline_reminder",
    "deadline_changed",
    "admission_help_requested",
    "admission_help_responded",
    "admission_comment_added",
    "admission_review_ready",
    "admission_affordability_signoff",
)
CONSTRAINT = "ck_notifications_type"


def _replace_constraint(types: tuple[str, ...]) -> None:
    """Resize ``type`` to the longest value and re-create its CHECK constraint.

    SQLAlchemy stores a non-native enum as ``VARCHAR(longest value)``; the longest
    admission type has 31 characters, so the column is widened with the constraint.
    """
    op.execute(f"ALTER TABLE notify.notifications DROP CONSTRAINT {CONSTRAINT}")
    op.alter_column(
        "notifications",
        "type",
        existing_type=sa.String(),
        type_=sa.String(length=max(len(value) for value in types)),
        existing_nullable=False,
        schema="notify",
    )
    values = ", ".join(f"'{value}'" for value in types)
    op.execute(
        f"ALTER TABLE notify.notifications "
        f"ADD CONSTRAINT {CONSTRAINT} CHECK (type IN ({values}))"
    )


def upgrade() -> None:
    """Allow the admission types."""
    _replace_constraint((*OLD_TYPES, *NEW_TYPES))


def downgrade() -> None:
    """Forbid the types again; its rows are deleted."""
    values = ", ".join(f"'{value}'" for value in NEW_TYPES)
    op.execute(f"DELETE FROM notify.notifications WHERE type IN ({values})")
    _replace_constraint(OLD_TYPES)
