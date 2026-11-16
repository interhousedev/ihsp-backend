"""What erasure removes outside the admission tables."""

from typing import Final

from app.shared.notifications import NotificationType

ADMISSION_NOTIFICATION_TYPES: Final = frozenset(
    {t for t in NotificationType if t.value.startswith("admission_")}
    | {
        NotificationType.DEADLINE_CHANGED,
        NotificationType.DOCUMENT_ATTACHED,
        NotificationType.DOCUMENT_REJECTED,
        NotificationType.TRANSCRIPT_READY,
        NotificationType.TRANSCRIPT_REMINDER,
        NotificationType.TRANSCRIPT_REQUESTED,
        NotificationType.TRANSCRIPT_SCAN_UPLOADED,
        NotificationType.TRANSCRIPT_UNROUTED,
    }
)
"""Notification types that only the admission platform sends."""
