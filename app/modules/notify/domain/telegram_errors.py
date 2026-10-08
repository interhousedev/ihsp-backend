"""Errors a TelegramSender raises, independent of the Telegram library."""


class TelegramSendError(Exception):
    """Base class of every sending failure."""


class TelegramBlocked(TelegramSendError):  # noqa: N818
    """The user blocked the bot, deactivated the account or the chat is gone."""


class TelegramRetryAfter(TelegramSendError):  # noqa: N818
    """Flood control: try again after `seconds`."""

    def __init__(self, seconds: float) -> None:
        """Remember how long Telegram asked us to wait."""
        self.seconds = seconds
        super().__init__(f"retry after {seconds}s")


class TelegramSendFailed(TelegramSendError):  # noqa: N818
    """Any other failure: bad request, server error, network error."""
