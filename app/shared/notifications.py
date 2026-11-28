"""Notification drafts written through the unit of work outbox."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession


class NotificationType(StrEnum):
    """Every notification type (spec → Models → Notification)."""

    MARKS = "marks"
    RESULT_DROP = "result_drop"
    RESULT_BELOW = "result_below"
    LESSON_RESOURCES = "lesson_resources"
    LESSON_PROMPT = "lesson_prompt"
    LESSON_CHANGED = "lesson_changed"
    MAIL = "mail"
    MAIL_BOUNCED = "mail_bounced"
    BROADCAST = "broadcast"
    EMIS_REAUTH = "emis_reauth"
    FILES_EXPIRING = "files_expiring"
    TELEGRAM_LINKED = "telegram_linked"
    OTP_RESET_REQUESTED = "otp_reset_requested"
    LOGIN_FAILURES = "login_failures"
    ACCOUNT_CLOSING = "account_closing"
    MAIL_SUSPENDED = "mail_suspended"
    SYNC_ALERT = "sync_alert"
    STUDENT_SYNC_FAILED = "student_sync_failed"
    KNOWLEDGE_GAP = "knowledge_gap"
    NOTEBOOK_ARTIFACT_READY = "notebook_artifact_ready"
    ASSESSMENT_REMINDER = "assessment_reminder"
    LIBRARY_ITEM_APPROVED = "library_item_approved"
    LIBRARY_ITEM_CHANGES_REQUESTED = "library_item_changes_requested"
    LIBRARY_ITEM_REJECTED = "library_item_rejected"
    LIBRARY_ITEM_UNPUBLISHED = "library_item_unpublished"
    LIBRARY_QUEUE_WAITING = "library_queue_waiting"
    LIBRARY_REPORT_FILED = "library_report_filed"
    LIBRARY_READING_LIST_NEW = "library_reading_list_new"
    LIBRARY_SUGGESTION_APPROVED = "library_suggestion_approved"
    LIBRARY_SUGGESTION_DECLINED = "library_suggestion_declined"
    CURATOR_EXAM_MARK = "curator_exam_mark"
    LESSON_ABSENCE = "lesson_absence"
    CURATOR_ABSENCES = "curator_absences"
    TEACHER_TEMPORARY_MARKS = "teacher_temporary_marks"
    FEEDBACK_NEW = "feedback_new"
    FEEDBACK_RESPONSE = "feedback_response"
    MCP_SCOPE_OFFER = "mcp_scope_offer"
    GATE_UNEXCUSED_EXIT = "gate_unexcused_exit"
    EXCUSE_REQUESTED = "excuse_requested"
    EXCUSE_DECIDED = "excuse_decided"
    EXCUSE_MESSAGE = "excuse_message"
    PRIVACY_UPDATE = "privacy_update"
    CHAT_ANSWER_READY = "chat_answer_ready"
    TRANSCRIPT_REQUESTED = "transcript_requested"
    TRANSCRIPT_REMINDER = "transcript_reminder"
    TRANSCRIPT_READY = "transcript_ready"
    TRANSCRIPT_SCAN_UPLOADED = "transcript_scan_uploaded"
    TRANSCRIPT_UNROUTED = "transcript_unrouted"
    ADMISSION_DOCUMENT_UPLOADED = "admission_document_uploaded"
    DOCUMENT_ATTACHED = "document_attached"
    DOCUMENT_REJECTED = "document_rejected"
    ADMISSION_DEADLINE_REMINDER = "admission_deadline_reminder"
    DEADLINE_CHANGED = "deadline_changed"
    ADMISSION_HELP_REQUESTED = "admission_help_requested"
    ADMISSION_HELP_RESPONDED = "admission_help_responded"
    ADMISSION_COMMENT_ADDED = "admission_comment_added"
    ADMISSION_REVIEW_READY = "admission_review_ready"
    ADMISSION_AFFORDABILITY_SIGNOFF = "admission_affordability_signoff"
    LMS_REVIEW_DUE = "lms_review_due"
    LMS_STREAK_AT_RISK = "lms_streak_at_risk"
    LMS_DEADLINE_SOON = "lms_deadline_soon"
    EVENT_REMINDER = "event_reminder"
    EVENT_CHANGED = "event_changed"
    EVENT_CANCELLED = "event_cancelled"
    EVENT_RATING_REQUEST = "event_rating_request"
    CLUB_ANNOUNCEMENT = "club_announcement"
    CLUB_JOIN_REQUEST = "club_join_request"
    CLUB_JOIN_RESULT = "club_join_result"
    CLUB_TRANSFER_OFFER = "club_transfer_offer"
    DRAFT_INVITE = "draft_invite"
    POSITION_APPLICATION_RESULT = "position_application_result"
    CLUB_OWNER_GRADUATING = "club_owner_graduating"
    HOMEWORK_SUBMITTED = "homework_submitted"
    HOMEWORK_REVIEWED = "homework_reviewed"


@dataclass(frozen=True, slots=True)
class NotificationDraft:
    """A notification to insert in the same transaction as the change."""

    user_id: UUID
    type: NotificationType
    payload: dict[str, Any]
    dedupe_key: str
    scheduled_at: datetime | None = None
    broadcast_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class AuditDraft:
    """An audit event to insert in the same transaction as the change."""

    type: str
    user_id: UUID | None = None
    actor_id: UUID | None = None
    ip: str | None = None
    user_agent: str | None = None
    metadata: dict[str, Any] | None = None


class NotificationOutbox(Protocol):
    """Writes notification drafts and withdraws one that has not been claimed yet."""

    async def write_notifications(
        self, session: AsyncSession, drafts: list[NotificationDraft]
    ) -> None:
        """Insert drafts as pending; a repeated `dedupe_key` is ignored."""
        ...

    async def cancel_pending(self, session: AsyncSession, dedupe_key: str) -> bool:
        """Cancel the notification with this key if it is still pending.

        Returns True only when the row was cancelled (it will never be sent). False
        means it was already claimed or sent, or does not exist; the caller must then
        not undo whatever the notification announced. Call it in the transaction of
        the state change, before that change.
        """
        ...
