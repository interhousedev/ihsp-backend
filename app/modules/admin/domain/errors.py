"""Errors of broadcasts."""

from app.shared.base_error import (
    BaseError,
    ConflictError,
    NotFoundError,
    ValidationFailedError,
)


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


class MigrationNotConfiguredError(ConflictError):
    """The host runner's shared directory is not set up on this deployment."""

    code = "admin/migration-not-configured"
    message_key = "admin-migration-not-configured"


class MigrationNotAllowedError(ConflictError):
    """The migration is in a phase that does not allow this action."""

    code = "admin/migration-not-allowed"
    message_key = "admin-migration-not-allowed"


class MigrationInvalidInputError(ValidationFailedError):
    """The target host, port, URL or pairing token is malformed."""

    code = "admin/migration-invalid-input"
    message_key = "admin-migration-invalid-input"


class BotNotFoundError(NotFoundError):
    """The Telegram bot is not registered."""

    code = "admin/bot-not-found"
    message_key = "admin-bot-not-found"


class BotAlreadyExistsError(ConflictError):
    """A bot with the same Telegram id is already registered."""

    code = "admin/bot-exists"
    message_key = "admin-bot-exists"


class BotTokenInvalidError(ValidationFailedError):
    """The token is malformed or Telegram rejected it (getMe)."""

    code = "admin/bot-token-invalid"
    message_key = "admin-bot-token-invalid"


class BotTokenMismatchError(ValidationFailedError):
    """A rotated token belongs to another Telegram bot."""

    code = "admin/bot-token-mismatch"
    message_key = "admin-bot-token-mismatch"


class BotDefaultTokenEnvError(ConflictError):
    """The default bot's token comes from the environment, not from Administration."""

    code = "admin/bot-default-token-env"
    message_key = "admin-bot-default-token-env"


class BotDefaultLockedError(ConflictError):
    """The default bot carries sign-in and the Mini App; it cannot be disabled."""

    code = "admin/bot-default-locked"
    message_key = "admin-bot-default-locked"


class BotFeatureUnknownError(ValidationFailedError):
    """A feature switch that does not exist."""

    code = "admin/bot-feature-unknown"
    message_key = "admin-bot-feature-unknown"


class BotNameInvalidError(ValidationFailedError):
    """The display name is empty or too long."""

    code = "admin/bot-name-invalid"
    message_key = "admin-bot-name-invalid"


class BotAnnouncementsOffError(ValidationFailedError):
    """A selected bot is disabled or has announcements switched off."""

    code = "admin/bot-announcements-off"
    message_key = "admin-bot-announcements-off"


class BotVaultUnavailableError(ConflictError):
    """Vault is not configured or not reachable; tokens cannot be stored."""

    code = "admin/bot-vault-unavailable"
    message_key = "admin-bot-vault-unavailable"


class BotTelegramUnavailableError(BaseError):
    """Telegram could not be reached to check the token; the token may be fine."""

    code = "admin/bot-telegram-unavailable"
    status = 503
    message_key = "admin-bot-telegram-unavailable"
