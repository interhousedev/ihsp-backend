"""Errors of broadcasts."""

from app.shared.base_error import ConflictError, NotFoundError, ValidationFailedError


class BroadcastNotFoundError(NotFoundError):
    """The broadcast does not exist."""

    code = "admin/broadcast-not-found"
    message_key = "notify-broadcast-not-found"


class BroadcastNotEditableError(ConflictError):
    """Only drafts and scheduled broadcasts can be edited."""

    code = "admin/broadcast-not-editable"
    message_key = "notify-broadcast-not-editable"


class BroadcastNotSendableError(ConflictError):
    """Only drafts and scheduled broadcasts can be sent."""

    code = "admin/broadcast-not-sendable"
    message_key = "notify-broadcast-not-sendable"


class BroadcastNotCancellableError(ConflictError):
    """Only scheduled broadcasts can be cancelled."""

    code = "admin/broadcast-not-cancellable"
    message_key = "notify-broadcast-not-cancellable"


class BroadcastEmptyAudienceError(ValidationFailedError):
    """The audience has no recipients."""

    code = "admin/broadcast-empty-audience"
    message_key = "notify-broadcast-empty-audience"


class BroadcastTextTooLongError(ValidationFailedError):
    """The message would not fit in one Telegram message."""

    code = "admin/broadcast-text-too-long"
    message_key = "notify-broadcast-text-too-long"


class BroadcastNoTelegramError(ValidationFailedError):
    """The admin has no Telegram account that can receive a preview."""

    code = "admin/broadcast-no-telegram"
    message_key = "notify-broadcast-no-telegram"


class BroadcastTimeInvalidError(ValidationFailedError):
    """The scheduled time has no time zone."""

    code = "admin/broadcast-time-invalid"
    message_key = "notify-broadcast-time-invalid"
