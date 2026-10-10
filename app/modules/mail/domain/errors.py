"""Typed errors of the mail module."""

from app.shared.base_error import (
    BaseError,
    ForbiddenError,
    GoneError,
    NotFoundError,
    RateLimitedError,
    ValidationFailedError,
)


class MailNotFoundError(NotFoundError):
    """No such mail in this mailbox."""

    code = "mail/not-found"
    message_key = "mail-not-found"


class MailPurgedError(GoneError):
    """The raw mail was deleted (30 days), so it cannot be used any more."""

    code = "mail/purged"
    message_key = "mail-purged"


class MailboxUnavailableError(ForbiddenError):
    """The user has no active mailbox."""

    code = "mail/mailbox-unavailable"
    message_key = "mail-mailbox-unavailable"


class MailSuspendedError(ForbiddenError):
    """Sending from this mailbox is suspended (MAIL-8)."""

    code = "mail/suspended"
    message_key = "mail-suspended"


class MailDailyLimitError(RateLimitedError):
    """The student sent the maximum number of mails today (MAIL-6)."""

    code = "mail/daily-limit"
    message_key = "mail-daily-limit"


class MailGlobalLimitError(RateLimitedError):
    """The whole system reached its daily sending cap (MAIL-6)."""

    code = "mail/global-limit"
    message_key = "mail-global-limit"


class InvalidRecipientError(ValidationFailedError):
    """A recipient address is not a valid email address."""

    code = "mail/invalid-recipient"
    message_key = "mail-invalid-recipient"


class NoRecipientsError(ValidationFailedError):
    """The mail has no recipients."""

    code = "mail/no-recipients"
    message_key = "mail-no-recipients"


class TooManyRecipientsError(ValidationFailedError):
    """The mail has more recipients than allowed (MAIL-6)."""

    code = "mail/too-many-recipients"
    message_key = "mail-too-many-recipients"


class MailTooLargeError(ValidationFailedError):
    """The composed mail is bigger than the relay accepts."""

    code = "mail/too-large"
    status = 413
    message_key = "mail-too-large"


class NotAnInboundMailError(ValidationFailedError):
    """Only received mails can be marked as spam."""

    code = "mail/not-inbound"
    message_key = "mail-not-inbound"


class OutboundMailDisabledError(ForbiddenError):
    """Sending email from the platform is switched off."""

    code = "mail/outbound-disabled"
    message_key = "mail-outbound-disabled"


class OutboundMailFailedError(BaseError):
    """The SMTP server did not take the email."""

    code = "mail/outbound-failed"
    status = 502
    message_key = "mail-outbound-failed"


class AttachmentNotFoundError(NotFoundError):
    """The attached file is not among the user's files."""

    code = "mail/attachment-not-found"
    message_key = "mail-attachment-not-found"
