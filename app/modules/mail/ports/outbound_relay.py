"""The external SMTP relay for outgoing mail (MAIL-6)."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol


class RelayTemporaryError(Exception):
    """The relay could not take the mail now (connection, 4xx); try again."""


class RelayPermanentError(Exception):
    """The relay refused the mail for good (5xx)."""


@dataclass(frozen=True, slots=True)
class RelayResult:
    """Recipients the relay refused while taking the mail for the others."""

    refused: tuple[str, ...] = ()


class OutboundRelay(Protocol):
    """Hands a finished message to the relay."""

    async def send(
        self, *, sender: str, recipients: Sequence[str], raw: bytes
    ) -> RelayResult:
        """Send the raw message.

        Raises:
            RelayTemporaryError: retry later.
            RelayPermanentError: do not retry.
        """
        ...
