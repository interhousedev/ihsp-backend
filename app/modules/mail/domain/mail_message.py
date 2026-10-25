"""The MailMessage entity: one mail in a student's mailbox."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from uuid import UUID

from app.modules.mail.domain.mail_meta import MailMeta
from app.modules.mail.domain.mail_status import MailDirection, MailStatus
from app.shared.contracts.mail import MailSummary

RETENTION = timedelta(days=30)
SNIPPET_LENGTH = 200


@dataclass(slots=True)
class MailMessage:
    """Headers, state and file references of one mail (the raw mail is a file)."""

    id: UUID
    user_id: UUID
    direction: MailDirection
    message_id: str
    from_address: str
    occurred_at: datetime
    status: MailStatus
    to: list[str] = field(default_factory=list)
    cc: list[str] = field(default_factory=list)
    subject: str = ""
    snippet: str = ""
    in_reply_to: str | None = None
    references: list[str] = field(default_factory=list)
    raw_file_id: UUID | None = None
    attachment_file_ids: list[UUID] = field(default_factory=list)
    spam_score: float | None = None
    meta: MailMeta = field(default_factory=MailMeta)

    def is_inbound(self) -> bool:
        """Return True for received mail."""
        return self.direction == MailDirection.IN

    def is_purged(self, now: datetime) -> bool:
        """Return True when the raw mail is gone (flagged, or older than 30 days)."""
        return self.meta.purged or self.occurred_at <= now - RETENTION

    def summary(self, now: datetime) -> MailSummary:
        """Return the list item for the bot."""
        return MailSummary(
            id=self.id,
            direction=self.direction.value,
            from_address=self.from_address,
            to=tuple(self.to),
            subject=self.subject,
            snippet=self.snippet,
            occurred_at=self.occurred_at,
            purged=self.is_purged(now),
        )

    def mark_bounced(self, now: datetime, reason: str | None) -> None:
        """Record a delivery failure reported by the remote server."""
        self.status = MailStatus.BOUNCED
        self.meta.bounced_at = now
        self.meta.bounce_reason = reason

    def mark_sent(self, now: datetime, refused: list[str]) -> None:
        """Record a hand-over to the relay."""
        self.status = MailStatus.SENT
        self.meta.sent_at = now
        self.meta.refused_recipients = refused

    def mark_failed(self, reason: str) -> None:
        """Record that the relay did not take the mail."""
        self.status = MailStatus.FAILED
        self.meta.failed_reason = reason[:500]
