"""SPF, DKIM and DMARC checks of an inbound message."""

from typing import Protocol

from app.modules.mail.domain.checks import InboundChecks


class InboundAuthenticator(Protocol):
    """Runs the enabled checks (settings toggles) for one message."""

    async def check(
        self, raw: bytes, *, peer_ip: str, mail_from: str, helo: str
    ) -> InboundChecks:
        """Return the results; a check that cannot run is ``none``/``temperror``."""
        ...
