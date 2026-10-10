"""The SMTP server for people-to-people email sent from the platform."""

from email.message import EmailMessage
from typing import Protocol


class OutboundSmtp(Protocol):
    """Hands a composed message to the SMTP server."""

    async def send(self, message: EmailMessage) -> None:
        """Send the message.

        Raises:
            OutboundMailFailedError: the server did not take it.
        """
        ...
