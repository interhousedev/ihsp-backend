"""Errors a PushSender raises, independent of the Web Push library."""


class PushSendError(Exception):
    """Base class of every push failure."""


class PushGone(PushSendError):  # noqa: N818
    """The push service says the subscription no longer exists (404 or 410)."""


class PushSendFailed(PushSendError):  # noqa: N818
    """Any other failure: rejected request, server error, network error."""
