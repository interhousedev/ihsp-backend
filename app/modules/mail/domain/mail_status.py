"""Direction and delivery state of a mail."""

from enum import StrEnum


class MailDirection(StrEnum):
    """Received (in) or sent (out) by the student."""

    IN = "in"
    OUT = "out"


class MailStatus(StrEnum):
    """README -> Models -> MailMessage.status."""

    RECEIVED = "received"
    SPAM = "spam"
    QUEUED = "queued"
    SENT = "sent"
    BOUNCED = "bounced"
    FAILED = "failed"
