"""Notification drafts written through the unit of work outbox."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID


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
