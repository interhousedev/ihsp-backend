"""Errors of the notification center."""

from app.shared.base_error import NotFoundError, ValidationFailedError


class NotificationNotFoundError(NotFoundError):
    """The notification does not exist or belongs to another user."""

    code = "notify/not-found"
    message_key = "notify-notification-not-found"


class InvalidPushSubscriptionError(ValidationFailedError):
    """The subscription's endpoint or keys are not acceptable."""

    code = "notify/invalid-push-subscription"
    message_key = "notify-push-subscription-invalid"
