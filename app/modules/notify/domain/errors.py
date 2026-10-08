"""Errors of the notification center."""

from app.shared.base_error import NotFoundError


class NotificationNotFoundError(NotFoundError):
    """The notification does not exist or belongs to another user."""

    code = "notify/not-found"
    message_key = "notify-notification-not-found"
