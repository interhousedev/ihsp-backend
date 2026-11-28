"""Club and event notification types.

Revision ID: notify_0023
Revises: notify_0022
Create Date: 2026-11-27 12:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "notify_0023"
down_revision: str | Sequence[str] | None = "notify_0022"
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
    "lms_review_due",
    "lms_streak_at_risk",
    "lms_deadline_soon",
)
NEW_TYPES = (
    "event_reminder",
    "event_changed",
    "event_cancelled",
    "event_rating_request",
    "club_announcement",
    "club_join_request",
    "club_join_result",
    "club_transfer_offer",
    "draft_invite",
    "position_application_result",
    "club_contact_message",
    "club_owner_graduating",
)
CONSTRAINT = "ck_notifications_type"


def _replace_constraint(types: tuple[str, ...]) -> None:
    """Re-create the CHECK constraint of ``type`` (the column stays 31 wide)."""
    op.execute(f"ALTER TABLE notify.notifications DROP CONSTRAINT {CONSTRAINT}")
    values = ", ".join(f"'{value}'" for value in types)
    op.execute(
        f"ALTER TABLE notify.notifications "
        f"ADD CONSTRAINT {CONSTRAINT} CHECK (type IN ({values}))"
    )


def upgrade() -> None:
    """Allow the club and event types."""
    _replace_constraint((*OLD_TYPES, *NEW_TYPES))


def downgrade() -> None:
    """Forbid the types again; their rows are deleted."""
    values = ", ".join(f"'{value}'" for value in NEW_TYPES)
    op.execute(f"DELETE FROM notify.notifications WHERE type IN ({values})")
    _replace_constraint(OLD_TYPES)
