"""Port: sending templated emails."""

from typing import Any, Protocol


class EmailSender(Protocol):
    """Sends one templated email (otp, activation, login_reminder, notice)."""

    async def send(
        self, to: str, template: str, params: dict[str, Any], locale: str
    ) -> None:
        """Render the template in the locale and send it.

        Raises:
            EmailDeliveryError: the relay refused or did not answer.
        """
        ...
